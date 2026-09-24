/** Whether the walkthrough was already seen in this browser. */
export const TOUR_KEY = "hqai.tour.v1";

export const tourSeen = (): boolean => {
  try {
    return globalThis.localStorage?.getItem(TOUR_KEY) === "done";
  } catch {
    return false;
  }
};
export const markTourSeen = (): void => {
  try {
    globalThis.localStorage?.setItem(TOUR_KEY, "done");
  } catch {
    // ignore
  }
};
