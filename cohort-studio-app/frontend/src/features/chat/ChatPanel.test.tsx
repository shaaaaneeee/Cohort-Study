import { ThemeProvider } from "@mui/material/styles";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProvider } from "../../api/context";
import type { ApiClient } from "../../api/client";
import { useStudyStore } from "../../store/studyStore";
import { META, chatResult, fakeClient } from "../../test/fixtures";
import { theme } from "../../theme/theme";
import { ChatPanel } from "./ChatPanel";

const initial = useStudyStore.getState();

function renderPanel(client: ApiClient) {
  return render(
    <ThemeProvider theme={theme}>
      <ApiProvider client={client}>
        <ChatPanel />
      </ApiProvider>
    </ThemeProvider>,
  );
}

const ASKING = chatResult({
  status: "asking",
  reply: "A few things first.",
  draft: null,
  model: null,
  questions: ["Which outcome?", "Over what follow-up?"],
  choices: [
    { question: "Which outcome?", options: ["Number of ED attendances", "Any ED attendance"] },
    { question: "Over what follow-up?", options: ["12 months", "6 months"] },
  ],
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  localStorage.clear();
  useStudyStore.setState(initial, true);
  useStudyStore.getState().setMeta(META);
});

describe("the assistant's options", () => {
  it("are shown as buttons and sent together as numbered answers", async () => {
    const chat = vi.fn().mockResolvedValueOnce(ASKING).mockResolvedValueOnce(chatResult());
    renderPanel(fakeClient({ chat }));
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "Does Programme A help patients?{Enter}");
    await user.click(await screen.findByRole("button", { name: "Any ED attendance" }));
    await user.click(screen.getByRole("button", { name: "6 months" }));
    await user.click(screen.getByRole("button", { name: "Send 2 answers" }));

    const second = chat.mock.lastCall?.[0] as { messages: { content: string }[] } | undefined;
    expect(second?.messages.at(-1)?.content).toBe("1. Any ED attendance\n2. 6 months");
  });

  it("send a single question's answer with one click", async () => {
    const one = chatResult({
      status: "asking",
      reply: "One question.",
      draft: null,
      model: null,
      questions: ["Which outcome?"],
      choices: [{ question: "Which outcome?", options: ["Number of ED attendances", "Any ED"] }],
    });
    const chat = vi.fn().mockResolvedValueOnce(one).mockResolvedValueOnce(chatResult());
    renderPanel(fakeClient({ chat }));
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "Help?{Enter}");
    await user.click(await screen.findByRole("button", { name: "Any ED" }));

    expect(chat).toHaveBeenCalledTimes(2);
    const second = chat.mock.lastCall?.[0] as { messages: { content: string }[] } | undefined;
    expect(second?.messages.at(-1)?.content).toBe("Any ED");
  });

  it("are not clickable on older messages", async () => {
    const chat = vi.fn().mockResolvedValueOnce(ASKING).mockResolvedValueOnce(chatResult());
    renderPanel(fakeClient({ chat }));
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Message"), "Help?{Enter}");
    await user.click(await screen.findByRole("button", { name: "Any ED attendance" }));
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await screen.findByText(/Here is the study/);

    expect(screen.queryByRole("button", { name: "Any ED attendance" })).toBeNull();
  });
});
