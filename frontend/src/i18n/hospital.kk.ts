/** Hospital mode copy (Kazakh): the same shape as `hospital`, checked by the type system. */
import type { hospital as ru } from "./hospital";

export const hospitalKk: typeof ru = {
  nav: "Стационар",
  title: "Стационар режимі",
  lead: (origin: string) =>
    `Бір стационар ${origin} кесінді күніне: модель алдағы 14 күнге не уәде етті, сол күні кезекте кім тұрды және кейін не болды.`,
  loading: "Стационар жүктелуде…",
  pick: {
    title: "Стационарды таңдаңыз",
    search: "Атауы бойынша іздеу",
    searchPlaceholder: "Атауын теріңіз",
    region: "Өңір",
    allRegions: "Бүкіл ел",
    showSmall: "Кезегі аз стационарларды да көрсету",
    smallTag: "деректер аз",
    smallHint:
      "Кезекте 20-дан аз жолдама: мұндай стационар бойынша қорытынды жасауға болмайды, бірақ ашуға болады.",
    found: (n: number) => `${n} стационар`,
    empty: "Ештеңе табылмады",
    emptyHint: "Сұранысты өзгертіңіз немесе басқа өңірді таңдаңыз.",
    waiting: (n: number) => `кезекте ${n}`,
    mapHint:
      "Стационарды басқару орталығының картасындағы нүктемен де таңдауға болады.",
    change: "Басқа стационар",
  },
  header: {
    origin: (date: string) => `Кесінді күні ${date}`,
    waiting: "кесінді күніне кезекте",
    profiles: "төсек бейіні",
    median: "күтудің медианасы",
    longest: "ең ұзақ күту",
    days: "күн",
    support: {
      SUFFICIENT: "кезек үлкен",
      LIMITED: "кезек шағын",
      SPARSE: "деректер аз",
    },
    sparseWarning:
      "Кезекте 20-дан аз жолдама. Төмендегі сандар нақты, бірақ мұндай таңдамада ешбір қорытынды тұрақты емес.",
  },
  profileSelect: {
    label: "Төсек бейіні",
    hint: "Ағын «стационар × бейін» жұбы бойынша жарияланады: әр бейіннің өз болжамы мен өз табалдырығы бар.",
    waiting: (n: number) => `кезекте ${n}`,
  },
  forecast: {
    title: "Не болады",
    subtitle: (origin: string) =>
      `${origin} күнінен бастап алдағы 14 күнге тіркеулердің жарияланған болжамы`,
    empty: "Бұл бейін бойынша болжам жарияланбаған.",
    emptyHint: "Басқа төсек бейінін таңдаңыз.",
    central: "болжам медианасы (p50)",
    band: "калибрленген 80% аралығы",
    threshold: "тарихи табалдырық",
    crossing: "бірінші асып кету",
    noThreshold: "табалдырық жарияланбаған",
    noCrossing: "14 күнде табалдырық асырылмайды",
    crossingOn: (date: string, lead: number) =>
      `${date} · кесіндіден кейін ${lead} күн`,
    severity: "сигнал деңгейі",
    severityNone: "сигнал жоқ",
    coverage: (pct: string) => `номиналды қамту ${pct}`,
    support: "қамтамасыз етілуі",
    facts: {
      threshold: "Табалдырық",
      crossing: "Бірінші асып кету",
      severity: "Сигнал",
      peak: "Болжам максимумы",
    },
  },
  waiting: {
    title: "Кім күтіп тұр",
    subtitle: (origin: string) =>
      `${origin} соңындағы жолдамалардың нақты кезегі, бірде-бір модель шамасынсыз`,
    totals: {
      waiting: "жолдама күтуде",
      profiles: "бейін",
      median: "күту медианасы, күн",
      longest: "ең ұзақ күту, күн",
    },
    byProfile: "Төсек бейіндері бойынша",
    byProfileHint: "Бейіннің стационар кезегіндегі үлесі.",
    histogram: "Қанша уақыт күтуде",
    histogramHint:
      "Кесінді күніне дейін кезекте өткізген күн саны бойынша жолдамалар.",
    bucket: (from: number, to: number | null) =>
      to === null ? `${from}+ күн` : `${from}–${to - 1} күн`,
    bucketCount: (n: number) => `${n} жолдама`,
    table: {
      title: "Жолдамалар кезегі",
      code: "Жолдама",
      profile: "Бейін",
      registered: "Тіркелген",
      waited: "Күтуде, күн",
      outcome: "Одан әрі не болды",
      sortLongest: "Ең ұзақ",
      sortShortest: "Ең қысқа",
      duplicate: "код дереккөзде қайталанады",
      page: (from: number, to: number, total: number) =>
        `${total} ішінен ${from}–${to}`,
      prev: "Артқа",
      next: "Алға",
      allProfiles: "Барлық бейіндер",
      noPredictions:
        "Мұнда модель бағалары жоқ: бұл жарияланым — өлшенген деректер. Оларға арналған бағандар бөлек қадамда пайда болады.",
    },
    outcome: {
      ADMITTED: "госпитализацияланды",
      REFUSED: "бас тартылды",
      STILL_WAITING_AT_CUTOFF: "әлі күтуде",
      on: (date: string, days: number) => `${date} · +${days} күн`,
    },
  },
  replay: {
    title: "Шын мәнінде не болды",
    subtitle: "18.03-тен 31.03-ке дейін күн сайын: болжамға қарсы факт",
    lead: "Әр күн кесінді күніне жарияланған аралықпен салыстырылады. Ештеңе кейін қайта есептелмейді.",
    notStarted: "Күн таңдалмаған",
    range: (from: string, to: string) => `${from} — ${to}`,
    day: (n: number) => `${n}-күн`,
    dayOf: (n: number, total: number) => `${total} ішінен ${n}`,
    start: "Қарау",
    pause: "Кідіріс",
    step: "Қадам",
    reset: "Басынан",
    inBand: "аралықта",
    outBand: "аралықтан тыс",
    above: "аралықтан жоғары",
    below: "аралықтан төмен",
    tally: (hit: number, total: number) => `${total} күннің ${hit}-і аралықта`,
    tallyPending: "«Қарау» не «Қадам» түймесін басыңыз",
    actual: "факт",
    expected: "болжам аралығы",
    columns: {
      date: "Күні",
      forecast: "Аралық",
      actual: "Факт",
      verdict: "Қорытынды",
    },
    empty: "Бұл бейін бойынша осы күндерге болжам да, факт та жоқ.",
  },
  hindsight: {
    tag: "ретроспектива",
    title: "Бұл — ретроспектива",
    note: (origin: string) =>
      `Нәтижелер ${origin} күнінен кейін белгілі болды. Кесінді күніне модель оларды білмеді және пайдалана алмады.`,
    short: (origin: string) => `${origin} кейін белгілі`,
  },
  errors: {
    unknown: "Стационар табылмады",
    unknownHint:
      "Кесінді күніне жарияланған кезекте бұл стационардың жолдамалары жоқ.",
    back: "Стационар таңдауға",
  },
};
