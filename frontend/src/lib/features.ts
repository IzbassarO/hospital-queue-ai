/** Short Russian label of a model feature; falls back to the API label. */
import { t } from "../i18n";

export const featureLabel = (feature: string, fallback: string) =>
  t.features[feature] ?? fallback;
