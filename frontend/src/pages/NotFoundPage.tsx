import { Link } from "react-router-dom";

import { t } from "../i18n";

export function NotFoundPage() {
  return (
    <div className="card space-y-3 p-6">
      <h1 className="text-2xl font-semibold">{t.errors.pageNotFound}</h1>
      <Link to="/" className="link">
        {t.errors.toOverview}
      </Link>
    </div>
  );
}
