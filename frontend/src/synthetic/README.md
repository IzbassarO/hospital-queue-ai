# Синтетический слой центра управления

Всё, что демо генерирует в браузере, лежит в этой папке. Продукт подключает её одной строкой — последним
`export … from "../synthetic"` в `src/tower/synthetic.ts`. Больше ни один модуль продукта эту папку не импортирует.

**Синтетическое** (создаётся из этих файлов и на экране подписано «синтетика»):

- очередь направлений `Н-####` вокруг опубликованных окон прогноза — `generate.ts: generatePatients`, параметры в
  `config.json → queue` (размер очереди, доля в окне прогноза, разброс ожидания, префикс и счётчик номеров);
- события 14-дневной симуляции: направления за день, запросы к специалисту, наблюдаемый поток на дату превышения,
  переносы госпитализаций, время событий — `config.json → simulation`; редьюсер `src/tower/sim/simulation.ts`
  читает только эти параметры и не содержит своих чисел;
- множители сценариев baseline / surge / season / outage, национальный множитель, вероятность эскалации, профили
  сезонного пика (регулярное выражение строкой) — `scenarios.json`;
- шум: `simulation.arrivalsNoise` (направления за день) и `simulation.observedNoiseLog` (наблюдаемый поток).

**Настоящее** (из опубликованной модели и реестра; здесь не читается и не меняется): прогнозы, ориентиры, уровни
серьёзности, даты первого превышения, ранги, реестр стационаров (названия, регионы, профили) и положение
стационаров на карте — оно выводится из реестра (`src/tower/geo/place.ts`), а не генерируется.

**Выключить слой** — одно из двух: `"enabled": false` в `config.json` или сборка/запуск с переменной окружения
`VITE_SYNTHETIC=off` (`VITE_SYNTHETIC=off npm run build`, `VITE_SYNTHETIC=off npm run dev`). Тогда центр
управления показывает только опубликованную модель: карту, уведомления и решения специалиста; очередь и
симуляция дней не генерируются, их место занимает подписанное пустое состояние.

**Изменить или расширить.** Числа — в `config.json`: каждое поле описано в типах `QueueParams` и
`SimulationParams` (`src/tower/synthetic.ts`). Сценарии — в `scenarios.json`; новый сценарий: добавить его id в
`ScenarioId` там же и подписи в `src/i18n/control.ts` и `control.kk.ts`, кнопка появится сама. Оба файла
проверяются при загрузке, неверное поле называет себя (`config.json.queue.windowShare: expected number`). `seed`
делает воспроизведение детерминированным; тест `src/test/synthetic.test.ts` сравнивает очередь и все четыре
сценария со слепком `src/test/fixtures/synthetic-baseline.json` — после намеренного изменения значений слепок
нужно перезаписать.

**Удалить папку.** В `src/tower/synthetic.ts` в последней строке заменить `"../synthetic"` на `"./synthetic-off"`,
удалить `src/synthetic/`, `src/test/synthetic.test.ts` и слепок. Продукт собирается и работает как в режиме
«выключено».

---

# Synthetic layer of the control centre

Everything the demo generates in the browser lives in this folder. The product imports it through one line: the
last `export … from "../synthetic"` in `src/tower/synthetic.ts`. No other product module imports this folder.

**Synthetic** (made from these files, labelled "synthetic" on screen):

- the queue of referrals `Н-####` around the published crossing windows — `generate.ts: generatePatients`,
  parameters in `config.json → queue` (queue size, share inside the forecast window, wait jitter, id prefix and
  counter);
- the events of the fourteen-day simulation: referrals of the day, requests to the specialist, observed flow on the
  crossing date, slipped admissions, event times — `config.json → simulation`; the reducer
  `src/tower/sim/simulation.ts` reads only these parameters and holds no numbers of its own;
- scenario multipliers for baseline / surge / season / outage, the national multiplier, the escalation chance and
  the seasonal profile pattern (a regular expression as a string) — `scenarios.json`;
- noise: `simulation.arrivalsNoise` (referrals per day) and `simulation.observedNoiseLog` (observed flow).

**Real** (from the published model and the registry; never read or changed here): forecasts, thresholds,
severities, first-crossing dates, ranks, the hospital registry (names, regions, profiles) and hospital positions on
the map, which are derived from the registry (`src/tower/geo/place.ts`), not generated.

**Switch the layer off** with either `"enabled": false` in `config.json` or the environment variable
`VITE_SYNTHETIC=off` at build or dev time (`VITE_SYNTHETIC=off npm run build`). The control centre then shows the
published model only: the map, the notifications and the specialist's decisions; the queue and the day simulation
are not generated and a labelled empty state takes their place.

**Edit or extend.** Numbers live in `config.json`; every field is described by the `QueueParams` and
`SimulationParams` types in `src/tower/synthetic.ts`. Scenarios live in `scenarios.json`; for a new one add its id
to `ScenarioId` there and its copy to `src/i18n/control.ts` and `control.kk.ts`, the chip appears by itself. Both
files are validated on load and a wrong field names itself (`config.json.queue.windowShare: expected number`).
`seed` keeps the replay deterministic; `src/test/synthetic.test.ts` compares the queue and all four scenarios with
the fixture `src/test/fixtures/synthetic-baseline.json`, which has to be re-captured after a deliberate change.

**Delete the folder.** In `src/tower/synthetic.ts` change `"../synthetic"` on the last line to `"./synthetic-off"`,
then delete `src/synthetic/`, `src/test/synthetic.test.ts` and the fixture. The product builds and behaves as in the
"off" mode.
