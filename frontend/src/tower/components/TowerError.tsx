/**
 * The error state of every control-centre page. It says what happened and what to do next: a fresh database with
 * no publication names the seed command, a missing API key names the variable and the command that creates it,
 * anything else keeps the API's own message. Always with a retry, never an endless spinner.
 */
import { API_BASE, ApiError } from "../../api/client";
import { t } from "../../i18n";

/** Swagger UI of the API: the same host as the API base, `/docs` in place of the versioned path. */
const apiDocsHref = () => `${API_BASE.replace(/\/api\/v\d+\/?$/, "")}/docs`;

export function TowerError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const api = error instanceof ApiError ? error : null;
  const kind =
    api?.status === 404
      ? "noPublication"
      : api?.kind === "auth" || api?.kind === "forbidden"
        ? "auth"
        : api?.kind === "network"
          ? "network"
          : "other";
  const states = t.control.states;
  return (
    <div className="scene-state tower-error" role="alert">
      {kind === "noPublication" ? (
        <>
          <h2>{states.noPublication.title}</h2>
          <p>{states.noPublication.body}</p>
          <pre className="tower-error-command" data-technical="true">
            <code>{states.noPublication.command}</code>
          </pre>
          <p>{states.noPublication.alt}</p>
          <pre className="tower-error-command" data-technical="true">
            <code>{states.noPublication.altCommand}</code>
          </pre>
          <p>
            {states.noPublication.docsHint}{" "}
            <a href={apiDocsHref()} data-technical="true">
              {states.noPublication.docs}
            </a>
          </p>
        </>
      ) : kind === "auth" ? (
        <>
          <h2>{states.auth.title}</h2>
          <p data-technical="true">{states.auth.body}</p>
        </>
      ) : (
        <>
          <h2>{states.failed}</h2>
          <p data-technical="true">
            {kind === "network" && api
              ? `${t.errors.network(api.url)} ${t.errors.networkHint}`
              : error instanceof Error
                ? error.message
                : t.tower.unavailable}
          </p>
        </>
      )}
      <button type="button" className="btn-ghost btn-sm" onClick={onRetry}>
        {states.retry}
      </button>
    </div>
  );
}
