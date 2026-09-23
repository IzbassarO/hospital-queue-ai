/** Scene identifiers and paths of the guided journey (shared by the layout, the scenes and tests). */
export const SCENES = [
  "detect",
  "understand",
  "test",
  "review",
  "trust",
] as const;
export type SceneId = (typeof SCENES)[number];
export const isScene = (value: string | undefined): value is SceneId =>
  SCENES.includes(value as SceneId);
export function scenePath(scene: SceneId, search = ""): string {
  return `/demo/${scene}${search}`;
}
