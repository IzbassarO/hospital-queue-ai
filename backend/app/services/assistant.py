"""Assistant proxy: the only place that talks to an external language model. The provider key stays here.

Every provider is used through its OpenAI-compatible chat endpoint (Groq, OpenRouter, Gemini and OpenAI itself
expose one), so a single request format serves them all. The system prompt keeps the product's claim boundaries:
the answer is an attention reading over the facts the browser sent, never an instruction.
"""

import json
import urllib.error
import urllib.request

from app.core.config import Settings
from app.schemas.specialist import AssistantReply, AssistantRequest, AssistantStatus

BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
}
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}

SYSTEM_PROMPT = {
    "ru": (
        "Ты ассистент специалиста по плановой госпитализации в Казахстане. Тебе дают опубликованные факты модели "
        "(прогноз потока направлений, обычный уровень, интервал, дата превышения, очередь) и детерминированное "
        "объяснение. Отвечай по-русски, коротко (3–5 предложений), только по этим фактам, ничего не выдумывай; "
        "вопросы не о сигнале вежливо отклоняй одной фразой. Объясняй, что показывает модель и почему сигнал получил "
        "свой уровень. Не советуй и не говори, что специалисту следует сделать, согласиться или нет: "
        "не используй слова "
        "«следует», «рекомендую», «нужно принять». Это оценка внимания, а не назначение: "
        "не давай медицинских "
        "рекомендаций, не распределяй пациентов, не говори о койках, вместимости и занятости. "
        "Последняя фраза: решение и ответственность за специалистом."
    ),
    "kk": (
        "Сен Қазақстандағы жоспарлы госпитализация маманының көмекшісісің. Саған модельдің жарияланған "
        "фактілері (жолдамалар ағынының болжамы, әдеттегі деңгей, аралық, асып кету күні, кезек) және "
        "детерминирленген түсіндірме беріледі. Қазақша, қысқа (3–5 сөйлем), тек осы фактілер бойынша жауап бер, "
        "ештеңе ойдан шығарма; сигналға қатысы жоқ сұрақтарды бір сөйлеммен сыпайы қайтар. Модель нені көрсететінін "
        "және сигнал неге осы деңгейді алғанын түсіндір. Кеңес берме және маман не істеуі керек екенін айтпа: "
        "«керек», «қажет», «ұсынамын», «тексеру керек» деген сөздерді қолданба; тексеру тізімін берме. "
        "Бұл назар аудару бағасы, тағайындау емес: "
        "медициналық ұсыныс берме, пациенттерді бөлме, төсек-орын, сыйымдылық және толымдылық туралы айтпа. "
        "Соңғы сөйлем: шешім мен жауапкершілік маманда."
    ),
}


class AssistantNotConfiguredError(Exception):
    """No provider key on the server; mapped to HTTP 503."""


class AssistantUpstreamError(Exception):
    """The provider answered with an error or unusable body; mapped to HTTP 502."""


def status(settings: Settings) -> AssistantStatus:
    configured = bool(settings.assistant_api_key)
    provider = settings.assistant_provider if configured else None
    return AssistantStatus(configured=configured, provider=provider, model=_model(settings) if configured else None)


def _model(settings: Settings) -> str:
    return settings.assistant_model or DEFAULT_MODELS.get(settings.assistant_provider, "gpt-4o-mini")


def _base_url(settings: Settings) -> str:
    return (settings.assistant_base_url or BASE_URLS.get(settings.assistant_provider, BASE_URLS["openai"])).rstrip("/")


def build_messages(request: AssistantRequest) -> list[dict[str, str]]:
    facts = "\n".join(f"- {f}" for f in request.facts) or "- (фактов не передано)"
    explanation = "\n".join(request.explanation) or "(объяснение не передано)"
    user = (
        f"Субъект: {request.subject.kind} {request.subject.id}, стационар «{request.subject.hospital}».\n"
        f"Факты:\n{facts}\n\nДетерминированное объяснение:\n{explanation}\n\nВопрос специалиста: {request.question}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT.get(request.lang, SYSTEM_PROMPT["ru"])},
        {"role": "user", "content": user},
    ]


def ask(settings: Settings, request: AssistantRequest, timeout: float = 40.0) -> AssistantReply:
    if not settings.assistant_api_key:
        raise AssistantNotConfiguredError("assistant is not configured (ASSISTANT_API_KEY is empty)")
    model = _model(settings)
    body = json.dumps(
        {"model": model, "messages": build_messages(request), "temperature": 0.3, "max_tokens": 600}
    ).encode()
    req = urllib.request.Request(
        f"{_base_url(settings)}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.assistant_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hospital-queue-ai/1.0 (+https://github.com/govtech-camp)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise AssistantUpstreamError(f"{settings.assistant_provider} answered HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AssistantUpstreamError(f"{settings.assistant_provider} unreachable: {exc}") from exc
    try:
        text = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise AssistantUpstreamError("provider reply has no choices[0].message.content") from exc
    if not text:
        raise AssistantUpstreamError("provider reply is empty")
    return AssistantReply(text=text, provider=settings.assistant_provider, model=model)
