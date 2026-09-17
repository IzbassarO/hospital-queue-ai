import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "../routes";
import { jsonResponse, mockApi } from "./mockApi";

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

let fetchMock: ReturnType<typeof mockApi>;
beforeEach(() => {
  fetchMock = mockApi();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("routes render with real API responses", () => {
  it("/ — national KPIs, source note and the regions table", async () => {
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Обзор по стране" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Источник: Министерство здравоохранения Республики Казахстан\..*Срез на 31\.03\.2025/,
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("роль: специалист")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Регионы" });
    const link = within(table).getByRole("link", { name: "г. Астана" });
    expect(link).toHaveAttribute("href", "/regions/71");
    // default sort: share of hospital profiles with high load, highest first
    const shareHeader = within(table).getByRole("columnheader", {
      name: /Доля профилей с высокой нагрузкой/,
    });
    expect(shareHeader).toHaveAttribute("aria-sort", "descending");
    const shares = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        Number(
          (row.lastElementChild?.textContent ?? "")
            .replace("%", "")
            .replace(",", "."),
        ),
      );
    expect(shares).toEqual([...shares].sort((a, b) => b - a));
    // max load index stays a column
    expect(
      within(table).getByRole("columnheader", { name: /Макс. индекс/ }),
    ).toBeInTheDocument();
  });

  it("/regions/:code — profile selector and hospitals of the selected profile", async () => {
    renderAt("/regions/71?profile=241");
    expect(
      await screen.findByRole("heading", { level: 1, name: "г. Астана" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Профиль койки")).toHaveValue("241");
    const table = await screen.findByRole("table", {
      name: "Стационары по профилю «Патологии беременности»",
    });
    const link = within(table).getAllByRole("link")[0];
    expect(link).toHaveAttribute("href", "/hospitals/ZIQ9/profiles/241");
    expect(within(table).getAllByText("Высокая").length).toBeGreaterThan(0);
  });

  it("/hospitals/:org/profiles/:profile — card, why panel, recommendations, decisions, referrals", async () => {
    renderAt("/hospitals/ZIQ9/profiles/241");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /Городской перинатальный центр/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("96,6")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Почему" })).toBeInTheDocument();
    expect(
      screen.getByText(/Производный прогноз очереди не показывается/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Решение принимает специалист. Система только предлагает.",
      ),
    ).toBeInTheDocument();
    expect(
      (await screen.findAllByText("оценка по историческим медианам")).length,
    ).toBeGreaterThan(0);
    expect(
      await screen.findByRole("table", { name: "История решений" }),
    ).toHaveTextContent("Подтверждено");
    expect(
      await screen.findByRole("table", {
        name: "Направления тестового периода",
      }),
    ).toBeInTheDocument();
  });

  it("confirming a recommendation POSTs /decisions with the actor and comment", async () => {
    const user = userEvent.setup();
    renderAt("/hospitals/ZIQ9/profiles/241");
    const [confirm] = await screen.findAllByRole("button", {
      name: "Подтвердить",
    });
    await user.click(confirm!);
    await user.type(screen.getByLabelText("Комментарий"), "Согласовано");
    await user.type(
      screen.getByLabelText(/Кто принимает решение/),
      "Иванова А.",
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          id: 6,
          created_at: "2026-09-16T10:00:00Z",
          region_code: "71",
          org_code: "ZIQ9",
          profile_code: "241",
          recommendation_id:
            "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
          alternative_org_code: "ZH7B",
          alternative_org_name: "Многопрофильная городская больница № 3",
          action: "confirm",
          comment: "Согласовано",
          actor: "Иванова А.",
          idempotency_key: "ui-test",
          api_key_label: "demo (DEMO_API_KEY)",
        },
        201,
      ),
    );
    await user.click(screen.getByRole("button", { name: "Записать решение" }));
    expect(
      await screen.findByText(/Решение записано: подтверждено/),
    ).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      action: "confirm",
      actor: "Иванова А.",
      comment: "Согласовано",
      org_code: "ZIQ9",
      region_code: "71",
      alternative_org_code: "ZH7B",
      idempotency_key: expect.stringMatching(/^ui-[0-9a-f-]{16,}$/),
    });
  });

  it("/alerts — reasons and links to the card", async () => {
    renderAt("/alerts");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Сигналы" }),
    ).toBeInTheDocument();
    const link = (
      await screen.findAllByRole("link", {
        name: /Городской перинатальный центр/,
      })
    )[0];
    expect(link).toHaveAttribute("href", "/hospitals/ZIQ9/profiles/241");
    expect(
      screen.getAllByText(/Индекс нагрузки 96,6 ≥ 70/).length,
    ).toBeGreaterThan(0);
    // caption built from the alert rule in GET /config
    expect(
      screen.getByText(/индексом нагрузки ≥ 70 .* 5 п\.п\. .* от 10 человек/),
    ).toBeInTheDocument();
  });

  it("/alerts — profile and status filters are sent to the API and kept in the URL", async () => {
    const user = userEvent.setup();
    const router = renderAt("/alerts");
    await screen.findAllByRole("link", {
      name: /Городской перинатальный центр/,
    });
    await user.selectOptions(await screen.findByLabelText("Статус"), "high");
    await user.selectOptions(screen.getByLabelText("Профиль"), "241");
    const last = String(
      fetchMock.mock.calls
        .filter(([u]) => String(u).includes("/alerts"))
        .at(-1)?.[0],
    );
    expect(last).toContain("status=high");
    expect(last).toContain("profile=241");
    expect(router.state.location.search).toBe("?profile=241&status=high");
  });

  it("card — «Скачать отчёт» fetches the export with the API client", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:report");
    const clickDownload = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    vi.stubGlobal(
      "URL",
      Object.assign(class extends URL {}, {
        createObjectURL,
        revokeObjectURL: vi.fn(),
      }),
    );
    renderAt("/hospitals/ZIQ9/profiles/241");
    await user.click(await screen.findByRole("button", { name: "PDF" }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
    const calls = fetchMock.mock.calls.filter(([u]) =>
      String(u).includes("/export"),
    );
    expect(calls).toHaveLength(1);
    expect(String(calls[0]?.[0])).toMatch(
      /\/api\/v1\/hospitals\/ZIQ9\/profiles\/241\/export\?format=pdf$/,
    );
    expect(clickDownload).toHaveBeenCalledOnce();
    expect(clickDownload.mock.instances[0]).toMatchObject({
      download: "hqai_card_ZIQ9_241_2025-03-31.pdf",
      href: "blob:report",
    });
  });

  it("/models — every model with its limitations", async () => {
    renderAt("/models");
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /A · Время ожидания/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /C · Прогноз/ }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "Ограничения" }),
    ).toHaveLength(3);
    expect(screen.getAllByRole("heading", { name: "Назначение" })).toHaveLength(
      3,
    );
    // baseline names come from the model card, not from English registry names
    expect(
      screen.getByText("Медиана по стационару и профилю"),
    ).toBeInTheDocument();
  });

  it("shows the URL it tried when the API is down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    renderAt("/");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      /API недоступен\. Адрес запроса: http:\/\/.+\/api\/v1\/overview/,
    );
  });
});
