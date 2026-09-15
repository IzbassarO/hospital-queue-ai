/** URL builders for in-app links (routes are declared in src/routes.tsx). */
const enc = encodeURIComponent;

export const regionPath = (code: string, profile?: string) =>
  profile
    ? `/regions/${enc(code)}?profile=${enc(profile)}`
    : `/regions/${enc(code)}`;

export const hospitalPath = (org: string, profile: string) =>
  `/hospitals/${enc(org)}/profiles/${enc(profile)}`;

export const alertsPath = (region?: string) =>
  region ? `/alerts?region=${enc(region)}` : "/alerts";
