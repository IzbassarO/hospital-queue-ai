/** Kazakh messages: the same shape as `ru`, checked by the type system. */
import { controlKk } from "./control.kk";
import { demoKk } from "./demo.kk";
import type { Messages } from "./ru";
import { towerKk } from "./tower.kk";

export const kk: Messages = {
  tower: towerKk,
  demo: demoKk,
  control: controlKk,
  app: {
    title: "Жоспарлы госпитализацияға кезек",
    subtitle: "Стационарлар жүктемесінің мониторингі",
    skipToContent: "Мазмұнға өту",
    role: (role: string) => `рөл: ${role}`,
    roleTitle: (label: string) => `API кілті: ${label}`,
    noKey: "API-ге қолжетімділік жоқ",
    footer:
      "ҚР Денсаулық сақтау министрлігінің ашық деректеріндегі прототип. Көрсеткіштер кесінді күніне есептелген, бұл нақты уақыттағы деректер емес.",
  },
  common: {
    noData: "—",
    loading: "Жүктелуде…",
    retry: "Қайталау",
    back: "Артқа",
    open: "Ашу",
  },
  units: {
    days: "күн",
    pp: "п.т.",
    ppPerWeek: "п.т./апта",
    percentPerWeek: "%/апта",
    people: "адам",
  },
  errors: {
    title: "Деректерді жүктеу мүмкін болмады",
    network: (url: string) => `API қолжетімсіз. Сұрау мекенжайы: ${url}`,
    networkHint:
      "Backend іске қосылғанын (make up) және /api/v1/health-ке жауап беретінін тексеріңіз.",
    http: (status: number, url: string) => `API жауабы ${status}, сұрау ${url}`,
    notFound: "Нысан табылмады",
    auth: "API қолжетімділік кілтін талап етеді: кілт берілмеген, қате немесе кері қайтарылған (VITE_API_KEY / DEMO_API_KEY).",
    forbidden: "Бұл әрекет үшін құқық жеткіліксіз.",
    shape: (url: string) => `API жауабы күтілетін пішімге сәйкес емес: ${url}`,
    pageNotFound: "Бет табылмады",
    toTower: "Басқару орталығына өту",
  },
};
