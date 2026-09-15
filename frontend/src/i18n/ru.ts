/**
 * Every user-visible string of the UI. Russian only for now; another language is a file with the same shape
 * (`Messages`) selected in ./index.ts. Texts about formulas and limitations follow docs/api.md and
 * docs/model_card.md — change them together.
 */
import type { DecisionAction, Status } from "../api/types";

const plural = (n: number, one: string, few: string, many: string) => {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
};

export const ru = {
  app: {
    title: "Очереди на плановую госпитализацию",
    subtitle: "Мониторинг нагрузки стационаров",
    skipToContent: "Перейти к содержимому",
    footer:
      "Прототип на открытых данных Министерства здравоохранения РК. Показатели рассчитаны на дату среза, это не данные в реальном времени.",
  },
  nav: {
    overview: "Обзор",
    alerts: "Сигналы",
    models: "О моделях",
    main: "Основная навигация",
    breadcrumbs: "Навигационная цепочка",
  },
  common: {
    noData: "—",
    loading: "Загрузка…",
    retry: "Повторить",
    back: "Назад",
    open: "Открыть",
    total: (n: number) => `Всего: ${n.toLocaleString("ru-RU")}`,
    page: (from: number, to: number, total: number) =>
      `${from.toLocaleString("ru-RU")}–${to.toLocaleString("ru-RU")} из ${total.toLocaleString("ru-RU")}`,
    prevPage: "Предыдущая страница",
    nextPage: "Следующая страница",
    pagination: "Постраничная навигация",
    sortAsc: "по возрастанию",
    sortDesc: "по убыванию",
    sortBy: (column: string) => `Сортировать по столбцу «${column}»`,
    asOf: (date: string) => `Данные на ${date}`,
    source: (date: string) =>
      `Источник: открытые данные МЗ РК (ИС «Бюро госпитализации», ЕРСБ). Срез на ${date}; окно показателей — последние 28 дней.`,
    hospitals: (n: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "стационар", "стационара", "стационаров")}`,
    referrals: (n: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "направление", "направления", "направлений")}`,
  },
  units: {
    days: "дн.",
    pp: "п.п.",
    ppPerWeek: "п.п./нед.",
    percentPerWeek: "%/нед.",
    people: "чел.",
  },
  status: {
    high: "Высокая",
    elevated: "Повышенная",
    normal: "Норма",
    insufficient_data: "Недостаточно данных",
  } satisfies Record<Status, string>,
  statusLong: {
    high: "Высокая нагрузка",
    elevated: "Повышенная нагрузка",
    normal: "Нормальная нагрузка",
    insufficient_data: "Недостаточно данных для индекса нагрузки",
  } satisfies Record<Status, string>,
  errors: {
    title: "Не удалось загрузить данные",
    network: (url: string) => `API недоступен. Адрес запроса: ${url}`,
    networkHint:
      "Проверьте, что backend запущен (make up) и отвечает на /api/v1/health.",
    http: (status: number, url: string) =>
      `Ответ API ${status} на запрос ${url}`,
    notBuilt: "Витрины данных ещё не построены: выполните make marts.",
    notFound: "Объект не найден",
    shape: (url: string) =>
      `Ответ API не соответствует ожидаемому формату: ${url}`,
    pageNotFound: "Страница не найдена",
    toOverview: "Перейти к обзору",
  },
  metrics: {
    queueNow: "Очередь сейчас",
    queueNowHint:
      "Направления, ожидающие госпитализации на конец дня среза (нижняя оценка)",
    medianWait: "Медиана ожидания",
    medianWaitHint: "Медиана дней от направления до госпитализации за 28 дней",
    refusalRate: "Доля отказов",
    refusalRateHint: "Отказы / (госпитализации + отказы) за 28 дней",
    hospitalsHighLoad: "Стационары с высокой нагрузкой",
    hospitalsHighLoadHint:
      "Стационары, у которых хотя бы один профиль имеет индекс нагрузки ≥ 70",
    backlog: "Срок рассасывания очереди",
    backlogShort: "Рассасывание",
    backlogHint:
      "Очередь / среднее число госпитализаций в день за 28 дней; не рассчитывается при < 0,5 в день",
    registrations28: "Направления за 28 дней",
    forecast14: "Прогноз направлений на 14 дней",
    forecast14Short: "Прогноз 14 дн.",
    loadIndex: "Индекс нагрузки",
    loadIndexMax: "Макс. индекс нагрузки",
    excessTrend: "Рост очереди сверх медианы",
    excessTrendShort: "Рост сверх медианы",
    excessTrendHint: (median: string) =>
      `Тренд очереди за 4 недели минус медианный тренд по стране (${median}), п.п. в неделю`,
    status: "Статус",
    hospital: "Стационар",
    region: "Регион",
    profile: "Профиль",
    hospitals: "Стационары",
    rank: (rank: number, n: number) => `Место ${rank} из ${n} в регионе`,
  },
  loadIndex: {
    components: "Составляющие индекса",
    backlog: "Срок рассасывания очереди",
    refusal: "Доля отказов",
    trend: "Рост очереди",
    weight: (w: number) => `вес ${w}%`,
    undefinedComponent: "не определена",
    formulaTitle: "Как считается индекс нагрузки",
    formula: [
      "Индекс от 0 до 100 показывает, насколько загружен стационар по профилю относительно других стационаров того же профиля по стране.",
      "Индекс = 100 × (0,60 · очередь + 0,25 · отказы + 0,15 · рост очереди), каждая составляющая от 0 до 1.",
      "Очередь — место по сроку рассасывания очереди среди стационаров того же профиля (1 — самый долгий срок).",
      "Отказы — доля отказов за 28 дней, делённая на 30% (30% и выше = 1).",
      "Рост очереди — превышение тренда очереди над медианой по стране, делённое на 20 п.п. в неделю; рост не быстрее медианы = 0.",
      "Если составляющая не определена, веса остальных пересчитываются. Индекс рассчитывается при не менее 10 направлениях за 28 дней. Высокая нагрузка — от 70, повышенная — от 40.",
    ],
  },
  overview: {
    title: "Обзор по стране",
    regionsTitle: "Регионы",
    regionsCaption: "Нажмите на регион, чтобы увидеть профили и стационары",
    columns: {
      region: "Регион",
      loadIndexMax: "Макс. индекс",
      queue: "Очередь",
      refusalRate: "Отказы",
      medianWait: "Медиана ожидания",
      highLoad: "Стационары с высокой нагрузкой",
    },
  },
  region: {
    kpisTitle: "Показатели региона",
    profileLabel: "Профиль койки",
    profileHint: "Профили отсортированы по индексу нагрузки региона",
    hospitalsTitle: (profile: string) => `Стационары по профилю «${profile}»`,
    hospitalsCaption:
      "По индексу нагрузки, от высокого к низкому. Нажмите на строку, чтобы открыть карточку.",
    noProfiles: "В регионе нет профилей с направлениями",
    noHospitals: "Нет стационаров по выбранному профилю",
    dayHospital: "дневной стационар",
    profileSummary: (n: number, high: number) =>
      `${n.toLocaleString("ru-RU")} ${plural(n, "стационар", "стационара", "стационаров")}, с высокой нагрузкой: ${high}`,
  },
  hospital: {
    kpisTitle: "Ключевые показатели",
    chartTitle: "Направления, госпитализации, отказы и очередь по дням",
    chartCaption: (from: string, to: string, fcTo: string) =>
      `Факт ${from} — ${to}, прогноз направлений и госпитализаций до ${fcTo}. Прогноз очереди не строится.`,
    today: "сегодня",
    series: {
      registrations: "Направления",
      hospitalizations: "Госпитализации",
      refusals: "Отказы",
      queue: "Очередь (правая шкала)",
      forecastRegistrations: "Прогноз направлений",
      forecastHospitalizations: "Прогноз госпитализаций",
    },
    chartTable: "Таблица данных графика",
    date: "Дата",
    noForecast: "Прогноз для этого стационара отсутствует",
    forecastMethod: {
      model: "модель C",
      region_share_fallback: "доля стационара в прогнозе региона",
    } as Record<string, string>,
    forecastMeta: (method: string, version: string) =>
      `Метод: ${method}; версия модели ${version}.`,
  },
  why: {
    title: "Почему",
    caption: (n: number) =>
      `Факторы, которые модели чаще всего связывают с прогнозами по ${n.toLocaleString("ru-RU")} ${plural(n, "направлению", "направлениям", "направлениям")} тестового периода (март 2025). Это связи в данных, а не причины.`,
    waitTitle: "Время ожидания",
    waitUnit: "среднее влияние на прогноз ожидания, дней",
    riskTitle: "Риск отказа",
    riskUnit: "среднее влияние на вероятность отказа, п.п.",
    typicalValue: "Типичное значение",
    share: (share: string) => `в топ-5 у ${share} направлений`,
    up: "увеличивает",
    down: "уменьшает",
    empty: "Нет направлений с прогнозами в тестовом периоде",
  },
  features: {
    region_code: "Регион пациента",
    hospital_region_code: "Регион стационара",
    org_code: "Стационар",
    profile_code: "Профиль койки",
    icd_chapter: "Класс диагноза",
    icd3: "Диагноз",
    referral_purpose: "Цель госпитализации",
    finance_source: "Финансирование",
    territorial_type: "Тип местности",
    registration_weekday: "День недели направления",
    day_of_window: "День периода данных",
    queue_hp_prev_day: "Очередь на дату направления",
    hosp_reg_7d: "Направления в стационар за 7 дней",
    hosp_reg_28d: "Направления в стационар за 28 дней",
    hosp_hosp_7d: "Госпитализации за 7 дней",
    hosp_hosp_28d: "Госпитализации за 28 дней",
    hp_median_wait_prev: "Медиана ожидания ранее",
    hp_n_hosp_prev: "Госпитализации по профилю ранее",
    hp_refusal_rate_prev: "Доля отказов ранее",
    hp_n_resolved_prev: "Завершённые направления ранее",
    ersb_throughput_per_day: "Выписки в день (ЕРСБ)",
    ersb_avg_los: "Средняя длительность пребывания (ЕРСБ)",
    adm_refusals_28d: "Отказы в приёмном покое за 28 дней",
    planned_lag_days: "Дней до плановой даты",
  } as Record<string, string>,
  recommendations: {
    title: "Рекомендации",
    humanDecides: "Решение принимает специалист. Система только предлагает.",
    methodBadge: "оценка по историческим медианам",
    notEligible: "Рекомендации не формируются",
    rule: (topPercent: number, delta: string) =>
      `Правило: стационар входит в ${topPercent}% самых загруженных в регионе; альтернативы — стационары того же региона и профиля с меньшим сроком рассасывания очереди и медианой ожидания меньше на ${delta} и более.`,
    waitCurrent: "Ожидание сейчас",
    waitAlternative: "Ожидание в альтернативе",
    delta: "Разница",
    deltaValue: (days: string) => `на ${days} меньше`,
    refusalCurrent: "Отказы сейчас",
    refusalAlternative: "Отказы в альтернативе",
    backlog: "Рассасывание очереди",
    backlogCompare: (current: string, alternative: string) =>
      `${alternative} против ${current}`,
    loadIndexAlternative: "Индекс нагрузки альтернативы",
    openCard: "Карточка альтернативы",
    alternativeTitle: (i: number) => `Альтернатива ${i}`,
    actions: {
      confirm: "Подтвердить",
      reject: "Отклонить",
      defer: "Отложить",
    } satisfies Record<DecisionAction, string>,
    form: {
      title: (action: string) => `${action}: запись решения`,
      comment: "Комментарий",
      commentPlaceholder: "Например: согласовано с заведующим отделением",
      actor: "Кто принимает решение",
      actorPlaceholder: "ФИО, организация",
      actorRequired: "Укажите, кто принимает решение",
      submit: "Записать решение",
      submitting: "Запись…",
      cancel: "Отмена",
      saved: "Решение записано",
      failed: "Не удалось записать решение",
    },
  },
  decisions: {
    title: "История решений",
    caption: "Решения по этому стационару и профилю, новые сверху",
    empty: "Решений пока нет",
    columns: {
      createdAt: "Дата и время",
      action: "Решение",
      alternative: "Альтернатива",
      actor: "Кто",
      comment: "Комментарий",
    },
    actionPast: {
      confirm: "Подтверждено",
      reject: "Отклонено",
      defer: "Отложено",
    } satisfies Record<DecisionAction, string>,
    general: "без рекомендации",
  },
  referrals: {
    title: "Направления тестового периода",
    caption:
      "Март 2025: прогнозы моделей A (ожидание) и B (риск отказа) по каждому направлению",
    sortLabel: "Сортировка",
    sortRisk: "по риску отказа",
    sortWait: "по прогнозу ожидания",
    columns: {
      date: "Дата направления",
      diagnosis: "Диагноз (МКБ-10)",
      purpose: "Цель",
      predWait: "Прогноз ожидания",
      refusalProb: "Вероятность отказа",
      details: "Объяснение",
    },
    highRisk: "высокий риск",
    expand: "Показать объяснение",
    collapse: "Скрыть объяснение",
    explanationWait: "Почему такой прогноз ожидания",
    explanationRisk: "Почему такой риск отказа",
    empty: "Нет направлений в тестовом периоде",
  },
  alerts: {
    title: "Сигналы",
    caption:
      "Стационары с индексом нагрузки ≥ 70 или очередью, растущей на 5 п.п. в неделю быстрее медианы по стране (при очереди от 10 человек)",
    regionFilter: "Регион",
    allRegions: "Все регионы",
    empty: "Сигналов нет",
    openCard: "Открыть карточку",
  },
  models: {
    title: "О моделях",
    intro:
      "Три модели обучены на направлениях января–февраля 2025 года и проверены на марте 2025 года. Ниже — их точность в сравнении с простыми правилами (базовыми линиями), рассчитанными на тех же данных.",
    version: "Версия",
    trainedAt: "Обучена",
    trainWindow: "Обучение",
    testWindow: "Проверка",
    population: "Данные проверки",
    metric: "Метрика",
    model: "Модель",
    bestBaseline: "Лучшая базовая линия",
    series: "Ряд",
    target: "Что прогнозируется",
    betterLower: "меньше — лучше",
    betterHigher: "больше — лучше",
    beatsYes:
      "Модель лучше сезонной наивной базовой линии во всех ячейках бэктеста",
    beatsNo: "Модель не везде лучше сезонной наивной базовой линии",
    limitationsTitle: "Ограничения",
    testRows: (n: number) => `${n.toLocaleString("ru-RU")} строк`,
    metricNames: {
      mae: "MAE, дней",
      wape: "WAPE",
      within_7d: "Ошибка не более 7 дней",
      spearman: "Корреляция Спирмена",
      roc_auc: "ROC-AUC",
      pr_auc: "PR-AUC",
      brier: "Brier",
      precision_top: "Точность в топ-10%",
    } as Record<string, string>,
    seriesSelection: "Отбор рядов по данным",
    backtestOrigins: "Точки прогноза в бэктесте",
    dataThrough: "Финальная модель обучена на данных до",
    // names that come from the model registry in English
    methodNames: {
      "B1 global median": "Медиана по стране",
      "B1 global rate": "Доля отказов по стране",
      "B2 median profile × patient region":
        "Медиана по профилю и региону пациента",
      "B2 rate profile × patient region":
        "Доля отказов по профилю и региону пациента",
      "B3 median hospital × profile (fallback B2)":
        "Медиана по стационару и профилю",
      "B3 rate hospital × profile (fallback B2)":
        "Доля отказов по стационару и профилю",
      "seasonal naive (same weekday)": "Сезонная наивная (тот же день недели)",
      "mean 28d": "Среднее за 28 дней",
      "mean 7d": "Среднее за 7 дней",
    } as Record<string, string>,
    seriesLevels: {
      "hospital × profile (fallback)":
        "стационар × профиль (малые ряды, доля региона)",
      "hospital × profile (modelled)": "стационар × профиль (модель)",
      "region × profile": "регион × профиль",
    } as Record<string, string>,
    targets: {
      registrations: "направления",
      hospitalizations: "госпитализации",
    } as Record<string, string>,
    limitations: {
      wait_time:
        "Два месяца обучения и один месяц проверки: сезонность не учтена. Ошибка выше всего в офтальмологии, кардиологии и неврологии, где ожидание долгое; в 4 из 20 регионов модель не лучше медианы по стационару и профилю. Прогноз отражает связи в исторических данных: «стационар X → +30 дней» не означает, что перенаправление пациента сократит ожидание.",
      refusal_risk:
        "Калибровка хорошая (расхождение по децилям не более 1 п.п.), но ранжирование слабее в Мангистауской, Акмолинской и Актюбинской областях. Модель использует регион и тип местности пациента: различия прогнозов между регионами отражают исторический доступ и не должны использоваться для понижения приоритета пациентов.",
      load_forecast:
        "Ошибки на уровне отдельного стационара высоки у любого метода, потому что дневные числа малы. Главный источник ошибок — праздники (неделя Наурыза): в обучении лишь несколько праздничных дней. Прогнозы стационаров не согласованы с прогнозами регионов. Прогноз очереди не показывается: в бэктесте он хуже, чем последнее известное значение.",
    } as Record<string, string>,
  },
};

export type Messages = typeof ru;
