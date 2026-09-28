/**
 * "Проверяемый ИИ": the transparency ledger inside the control centre. Two verifications side by side and kept
 * distinct — the server's (chain + every covered database row, with the private salts) and the browser's own (the
 * public export, re-hashed here with Web Crypto, never trusting the server's verdict) — then the recent entries, a
 * lookup by number, receipt hash or subject, and what is and is not being claimed. docs/transparency-ledger.md.
 *
 * Deep link from a decision receipt: /verify?seq=1427 opens that entry.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  transparencyApi,
  useLedgerEntries,
  useLedgerHead,
  useServerVerification,
  type LedgerEntryItem,
  type LedgerVerification,
} from "../api/transparency";
import { t } from "../i18n";
import { entryHash, verifyExport, type ChainVerdict } from "./chain";
import { HashValue } from "./HashValue";
import { eventLabel, ledgerTime, reasonLabel } from "./labels";
import {
  forgetTrustedHead,
  loadTrustedHead,
  saveTrustedHead,
  type StoredHead,
} from "./trusted";

/** Local time as DD.MM.YYYY HH:MM:SS in both languages (browsers without kk-KZ data fall back to US order). */
const pad = (n: number) => String(n).padStart(2, "0");
const localTime = (iso: string) => {
  const d = new Date(iso);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

type Status = "ok" | "broken" | "running" | "idle";

function StatusBadge({ status }: { status: Status }) {
  return (
    <p className={`verify-badge is-${status}`} role="status">
      <span className="verify-badge-dot" aria-hidden="true" />
      {t.verify.status[status]}
    </p>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="verify-fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Failure({
  seq,
  code,
  subject,
}: {
  seq: number | null;
  code: string | null;
  subject: string | null;
}) {
  return (
    <div className="verify-failure" role="alert">
      <Fact label={t.verify.facts.failure}>
        {seq === null ? "—" : t.verify.seq(seq)}
      </Fact>
      <Fact label={t.verify.facts.reason}>
        {reasonLabel(code)} <code className="verify-code">{code}</code>
      </Fact>
      {subject ? (
        <Fact label={t.verify.facts.subject}>
          <code className="verify-code">{subject}</code>
        </Fact>
      ) : null}
    </div>
  );
}

function ServerCard({
  report,
  loading,
  error,
  onRerun,
}: {
  report: LedgerVerification | undefined;
  loading: boolean;
  error: unknown;
  onRerun: () => void;
}) {
  const status: Status = loading
    ? "running"
    : report
      ? report.status === "OK"
        ? "ok"
        : "broken"
      : "idle";
  return (
    <section
      className={`verify-card is-${status}`}
      aria-labelledby="verify-server-title"
      data-testid="server-verification"
    >
      <header className="verify-card-head">
        <h2 id="verify-server-title">{t.verify.server.title}</h2>
        <StatusBadge status={status} />
      </header>
      <p className="verify-card-lead">{t.verify.server.lead}</p>
      {error && !report ? (
        <p className="verify-error" role="alert">
          {error instanceof Error ? error.message : t.verify.unavailable}
        </p>
      ) : null}
      {report ? (
        <>
          <dl className="verify-facts">
            <Fact label={t.verify.facts.chainLength}>
              {report.chain_length}
            </Fact>
            <Fact label={t.verify.facts.verifiedThrough}>
              {t.verify.seq(report.verified_through_seq)}
            </Fact>
            <Fact label={t.verify.facts.lastCheck}>
              {localTime(report.verified_at)}
            </Fact>
            <Fact label={t.verify.facts.duration}>
              {t.verify.browser.duration(report.duration_ms)}
            </Fact>
            {report.head_hash ? (
              <Fact label={t.verify.facts.head}>
                <HashValue hash={report.head_hash} />
              </Fact>
            ) : null}
          </dl>
          {report.status === "BROKEN" ? (
            <Failure
              seq={report.failure_seq}
              code={report.reason_code}
              subject={report.subject}
            />
          ) : null}
          <p className="verify-note">
            {t.verify.server.covered(
              report.covered_decisions,
              report.covered_publications,
            )}
          </p>
        </>
      ) : null}
      <div className="verify-card-actions">
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={onRerun}
          disabled={loading}
        >
          {t.verify.server.rerun}
        </button>
      </div>
    </section>
  );
}

interface BrowserState {
  status: Status;
  verdict: ChainVerdict | null;
  trusted: StoredHead | null;
  error: string | null;
}

function useBrowserVerification() {
  const [state, setState] = useState<BrowserState>({
    status: "idle",
    verdict: null,
    trusted: null,
    error: null,
  });
  const exportText = useRef<string | null>(null);
  // one run at a time, and none that outlives the page: a run left over from an unmounted page must not overwrite
  // the remembered head a later run is checking against
  const busy = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const run = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setState((s) => ({ ...s, status: "running", error: null }));
    try {
      const text = await transparencyApi.exportText();
      exportText.current = text;
      const trusted = loadTrustedHead();
      const verdict = await verifyExport(text, trusted);
      if (!mounted.current) return;
      if (verdict.status === "OK" && verdict.headSeq && verdict.headHash)
        saveTrustedHead({
          seq: verdict.headSeq,
          hash: verdict.headHash,
          seenAt: new Date().toISOString(),
        });
      setState({
        status: verdict.status === "OK" ? "ok" : "broken",
        verdict,
        trusted,
        error: null,
      });
    } catch (error) {
      setState({
        status: "idle",
        verdict: null,
        trusted: null,
        error:
          error instanceof ApiError || error instanceof Error
            ? error.message
            : String(error),
      });
    } finally {
      busy.current = false;
    }
  }, []);
  return { state, run, exportText };
}

function BrowserCard({
  state,
  serverHead,
  onRun,
  onForget,
}: {
  state: BrowserState;
  serverHead: string | null;
  onRun: () => void;
  onForget: () => void;
}) {
  const verdict = state.verdict;
  return (
    <section
      className={`verify-card is-${state.status}`}
      aria-labelledby="verify-browser-title"
      data-testid="browser-verification"
    >
      <header className="verify-card-head">
        <h2 id="verify-browser-title">{t.verify.browser.title}</h2>
        <StatusBadge status={state.status} />
      </header>
      <p className="verify-card-lead">{t.verify.browser.lead}</p>
      {state.error ? (
        <p className="verify-error" role="alert">
          {state.error}
        </p>
      ) : null}
      {verdict ? (
        <>
          <dl className="verify-facts">
            <Fact label={t.verify.facts.entries}>{verdict.entries}</Fact>
            <Fact label={t.verify.facts.verifiedThrough}>
              {t.verify.seq(verdict.verifiedThroughSeq)}
            </Fact>
            <Fact label={t.verify.facts.engine}>
              {t.verify.browser.engine[verdict.engine]}
            </Fact>
            <Fact label={t.verify.facts.duration}>
              {t.verify.browser.duration(verdict.durationMs)}
            </Fact>
            {verdict.headHash ? (
              <Fact label={t.verify.facts.head}>
                <HashValue hash={verdict.headHash} />
              </Fact>
            ) : null}
          </dl>
          {verdict.status === "BROKEN" ? (
            <Failure
              seq={verdict.failureSeq}
              code={verdict.reasonCode}
              subject={null}
            />
          ) : null}
          {verdict.status === "OK" && serverHead && verdict.headHash ? (
            <p
              className={`verify-note ${serverHead === verdict.headHash ? "is-ok" : "is-warn"}`}
            >
              {serverHead === verdict.headHash
                ? t.verify.browser.matchesServer
                : t.verify.browser.differsFromServer}
            </p>
          ) : null}
          {verdict.status === "OK" ? (
            <p className="verify-note">
              {state.trusted && verdict.trustedHeadChecked
                ? t.verify.browser.trusted(
                    state.trusted.seq,
                    localTime(state.trusted.seenAt),
                  )
                : t.verify.browser.trustedFirst}
            </p>
          ) : null}
        </>
      ) : null}
      <div className="verify-card-actions">
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={onRun}
          disabled={state.status === "running"}
        >
          {t.verify.browser.run}
        </button>
        {state.trusted || verdict?.status === "OK" ? (
          <button type="button" className="btn-link btn-sm" onClick={onForget}>
            {t.verify.browser.forget}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function EntryDetail({ entry }: { entry: LedgerEntryItem }) {
  const [recomputed, setRecomputed] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    entryHash(entry)
      .then((hash) => live && setRecomputed(hash === entry.entry_hash))
      .catch(() => live && setRecomputed(false));
    return () => {
      live = false;
    };
  }, [entry]);
  const hasCommitments = "commitments" in entry.payload;
  return (
    <article className="verify-entry" data-testid="ledger-entry">
      <header className="verify-entry-head">
        <span className="verify-seq">{t.verify.seq(entry.seq)}</span>
        <strong>{eventLabel(entry)}</strong>
        <span className="verify-entry-time">
          {ledgerTime(entry.created_at)}
        </span>
      </header>
      <dl className="verify-facts">
        <Fact label={t.verify.facts.subject}>
          <code className="verify-code">{entry.subject}</code>
        </Fact>
        <Fact label="SHA-256">
          <HashValue hash={entry.entry_hash} />
        </Fact>
        <Fact label={t.verify.lookup.prev}>
          <HashValue hash={entry.prev_hash} />
        </Fact>
      </dl>
      {recomputed !== null ? (
        <p
          className={`verify-note ${recomputed ? "is-ok" : "is-warn"}`}
          role="status"
        >
          {recomputed
            ? t.verify.lookup.recomputed
            : t.verify.lookup.recomputeFailed}
        </p>
      ) : null}
      <details className="verify-payload">
        <summary>{t.verify.lookup.payload}</summary>
        <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
        {hasCommitments ? (
          <p className="verify-note">{t.verify.lookup.commitmentsNote}</p>
        ) : null}
      </details>
    </article>
  );
}

async function findEntries(query: string): Promise<LedgerEntryItem[]> {
  const q = query.trim();
  if (/^№?\d+$/.test(q)) {
    try {
      return [await transparencyApi.entry(Number(q.replace("№", "")))];
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return [];
      throw error;
    }
  }
  if (/^[0-9a-fA-F]{8,64}$/.test(q))
    return transparencyApi.lookup({ entry_hash: q.toLowerCase() });
  return transparencyApi.lookup({ subject: q });
}

/** A number, a hash of at least 8 hex characters, or a subject "kind:id". */
const lookupValid = (q: string) =>
  /^№?\d+$/.test(q) || /^[0-9a-fA-F]{8,64}$/.test(q) || /^[^\s:]+:\S+$/.test(q);

function Lookup({ initial }: { initial: string }) {
  const [query, setQuery] = useState(initial);
  const [submitted, setSubmitted] = useState(initial.trim());
  const [invalid, setInvalid] = useState(false);
  const found = useQuery({
    queryKey: ["transparency", "lookup", submitted],
    queryFn: () => findEntries(submitted),
    enabled: submitted !== "" && lookupValid(submitted),
    retry: false,
  });
  return (
    <section className="verify-section" aria-labelledby="verify-lookup-title">
      <h2 id="verify-lookup-title" className="verify-section-title">
        {t.verify.lookup.title}
      </h2>
      <form
        className="verify-lookup"
        onSubmit={(e) => {
          e.preventDefault();
          const q = query.trim();
          setInvalid(!lookupValid(q));
          if (lookupValid(q)) setSubmitted(q);
        }}
      >
        <label htmlFor="verify-lookup-input">{t.verify.lookup.label}</label>
        <div className="verify-lookup-row">
          <input
            id="verify-lookup-input"
            type="search"
            value={query}
            placeholder={t.verify.lookup.placeholder}
            onChange={(e) => setQuery(e.target.value)}
            spellCheck={false}
            autoComplete="off"
          />
          <button type="submit" className="btn-accent btn-sm">
            {t.verify.lookup.submit}
          </button>
        </div>
        <p className="verify-hint">{t.verify.lookup.hint}</p>
      </form>
      {invalid ? (
        <p className="verify-error" role="alert">
          {t.verify.lookup.invalid}
        </p>
      ) : found.isFetching ? (
        <p role="status">{t.common.loading}</p>
      ) : found.isError ? (
        <p className="verify-error" role="alert">
          {found.error instanceof Error
            ? found.error.message
            : String(found.error)}
        </p>
      ) : found.data ? (
        found.data.length === 0 ? (
          <p role="status">{t.verify.lookup.notFound}</p>
        ) : (
          <div className="verify-results">
            <p className="verify-hint" role="status">
              {t.verify.lookup.result(found.data.length)}
            </p>
            {found.data.map((entry) => (
              <EntryDetail key={entry.seq} entry={entry} />
            ))}
          </div>
        )
      ) : null}
    </section>
  );
}

function Recent({
  entries,
  onOpen,
}: {
  entries: LedgerEntryItem[];
  onOpen: (seq: number) => void;
}) {
  return (
    <section className="verify-section" aria-labelledby="verify-recent-title">
      <h2 id="verify-recent-title" className="verify-section-title">
        {t.verify.recent.title}
      </h2>
      {entries.length <= 1 ? (
        <p className="verify-hint">{t.verify.recent.empty}</p>
      ) : null}
      <ol className="verify-recent" data-testid="recent-entries">
        {entries.map((entry) => (
          <li key={entry.seq}>
            <button
              type="button"
              className="verify-recent-row"
              onClick={() => onOpen(entry.seq)}
              aria-label={`${t.verify.recent.open} ${t.verify.seq(entry.seq)}: ${eventLabel(entry)}`}
            >
              <span className="verify-seq">{t.verify.seq(entry.seq)}</span>
              <span className="verify-recent-event">{eventLabel(entry)}</span>
              <span className="verify-recent-time">
                {ledgerTime(entry.created_at)}
              </span>
              <code className="verify-recent-subject">{entry.subject}</code>
              <code className="verify-recent-hash">
                {entry.entry_hash.slice(0, 12)}…
              </code>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Explain() {
  const e = t.verify.explain;
  return (
    <section className="verify-explain" aria-label={e.title}>
      <div>
        <h3>{e.verified.title}</h3>
        <ul>
          {e.verified.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <div>
        <h3>{e.notClaimed.title}</h3>
        <ul>
          {e.notClaimed.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <div className="verify-explain-human">
        <h3>{e.human.title}</h3>
        <p>{e.human.body}</p>
        <p className="verify-motto">{t.verify.motto}</p>
      </div>
    </section>
  );
}

function download(text: string, seq: number | null): void {
  const url = URL.createObjectURL(
    new Blob([text], { type: "application/x-ndjson" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `aqyl-kezek-transparency-ledger${seq ? `-${seq}` : ""}.jsonl`;
  link.click();
  URL.revokeObjectURL(url);
}

export function VerifyPage() {
  const [params, setParams] = useSearchParams();
  const initialSeq = params.get("seq") ?? "";
  const head = useLedgerHead();
  const server = useServerVerification();
  const recent = useLedgerEntries(12);
  const browser = useBrowserVerification();
  const { run } = browser;
  useEffect(() => {
    void run();
  }, [run]);
  const serverHead = useMemo(
    () => server.data?.head_hash ?? head.data?.entry_hash ?? null,
    [server.data, head.data],
  );
  const onOpen = (seq: number) => {
    setParams({ seq: String(seq) });
    document
      .getElementById("verify-lookup-title")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const onDownload = async () => {
    const text =
      browser.exportText.current ?? (await transparencyApi.exportText());
    download(text, browser.state.verdict?.headSeq ?? null);
  };
  const unavailable = head.isError && server.isError;
  return (
    <div className="verify-page">
      <section className="tower-lead verify-lead">
        <div className="tower-lead-text">
          <p className="verify-kicker">{t.verify.kicker}</p>
          <h1>{t.verify.title}</h1>
          <p>{t.verify.lead}</p>
        </div>
        <div className="verify-lead-actions">
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => void onDownload()}
          >
            {t.verify.download}
          </button>
          <p className="verify-hint">
            {t.verify.offlineHint}{" "}
            <code className="verify-code">
              python3 tools/ledger_verify.py ledger.jsonl
            </code>
          </p>
        </div>
      </section>
      {unavailable ? (
        <p className="verify-error" role="alert">
          {t.verify.unavailable}
        </p>
      ) : null}
      <div className="verify-cards">
        <ServerCard
          report={server.data}
          loading={server.isFetching}
          error={server.error}
          onRerun={() => void server.refetch()}
        />
        <BrowserCard
          state={browser.state}
          serverHead={serverHead}
          onRun={() => void run()}
          onForget={() => {
            forgetTrustedHead();
            void run();
          }}
        />
      </div>
      <div className="verify-columns">
        <Recent entries={recent.data?.items ?? []} onOpen={onOpen} />
        <Lookup key={initialSeq} initial={initialSeq} />
      </div>
      <Explain />
    </div>
  );
}
