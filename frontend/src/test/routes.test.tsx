import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
afterEach(() => vi.unstubAllGlobals());

describe("routes render with real API responses", () => {
  it("/ — national KPIs, source note and the regions table", async () => {
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Обзор по стране" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Источник: открытые данные МЗ РК.*31\.03\.2025/),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Регионы" });
    const link = within(table).getByRole("link", { name: "г. Астана" });
    expect(link).toHaveAttribute("href", "/regions/71");
    // sorted by load_index_max, highest first
    const firstRow = within(table).getAllByRole("row")[1];
    expect(firstRow).toHaveTextContent("г. Астана");
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
          action: "confirm",
          comment: "Согласовано",
          actor: "Иванова А.",
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
