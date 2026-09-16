import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("exposes the run id before consuming stream events", async () => {
    vi.stubGlobal("window", {});
    const order: string[] = [];
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            '{"type":"message.completed","message_id":"m1","lane":"primary"}\n',
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(body, {
        status: 200,
        headers: {
          "content-type": "application/x-ndjson",
          "x-run-id": "run-123",
        },
      })),
    );

    const result = await streamChat(
      {
        conversation_id: "conversation-1",
        content: "hello",
        model_id: "phi4-mini",
      },
      new AbortController().signal,
      () => order.push("event"),
      (runId) => order.push(`run:${runId}`),
    );

    expect(result).toBe("run-123");
    expect(order).toEqual(["run:run-123", "event"]);
  });
});
