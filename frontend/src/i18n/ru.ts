/**
 * Every user-visible string of the UI. Russian only for now; another language is a file with the same shape
 * (`Messages`) selected in ./index.ts. Scientific values always come from the API; these are frames only.
 */
import { control } from "./control";
import { demo } from "./demo";
import { tower } from "./tower";

export const ru = {
  tower,
  demo,
  control,
  app: {
    title: "Очереди на плановую госпитализацию",
    subtitle: "Мониторинг нагрузки стационаров",
    skipToContent: "Перейти к содержимому",
    role: (role: string) => `роль: ${role}`,
    roleTitle: (label: string) => `API-ключ: ${label}`,
    noKey: "нет доступа к API",
    footer:
      "Прототип на открытых данных Министерства здравоохранения РК. Показатели рассчитаны на дату среза, это не данные в реальном времени.",
  },
  common: {
    noData: "—",
    loading: "Загрузка…",
    retry: "Повторить",
    back: "Назад",
    open: "Открыть",
  },
  units: {
    days: "дн.",
    pp: "п.п.",
    ppPerWeek: "п.п./нед.",
    percentPerWeek: "%/нед.",
    people: "чел.",
  },
  errors: {
    title: "Не удалось загрузить данные",
    network: (url: string) => `API недоступен. Адрес запроса: ${url}`,
    networkHint:
      "Проверьте, что backend запущен (make up) и отвечает на /api/v1/health.",
    http: (status: number, url: string) =>
      `Ответ API ${status} на запрос ${url}`,
    notFound: "Объект не найден",
    auth: "API требует ключ доступа: ключ не задан, неверен или отозван (VITE_API_KEY / DEMO_API_KEY).",
    forbidden: "Недостаточно прав для этого действия.",
    shape: (url: string) =>
      `Ответ API не соответствует ожидаемому формату: ${url}`,
    pageNotFound: "Страница не найдена",
    toTower: "Перейти в центр управления",
  },
};

export type Messages = typeof ru;
