import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useApi } from "../../api/context";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useStudyStore, type ChatEntry } from "../../store/studyStore";
import { DraftCard } from "./DraftCard";

const EXAMPLES = [
  "Does Programme A reduce ED attendances in the 12 months after enrolment, adjusting for prior ED use, age and gender?",
  "Does Programme A help patients?",
  "Does Programme A reduce mortality?",
];

function AssistantMessage({ entry }: { entry: ChatEntry }) {
  const paragraphs = (entry.reply ?? entry.content).split(/\n{2,}/).filter(Boolean);
  if (entry.status === "unsupported") {
    return (
      <Alert severity="info" variant="outlined">
        <AlertTitle>This dataset can't answer that</AlertTitle>
        {paragraphs.map((p, i) => (
          <Typography key={i} variant="body2" sx={{ mb: 0.5 }}>
            {p}
          </Typography>
        ))}
      </Alert>
    );
  }
  return (
    <Box>
      {paragraphs.map((p, i) => (
        <Typography key={i} variant="body2" sx={{ mb: 1, whiteSpace: "pre-wrap" }}>
          {p}
        </Typography>
      ))}
      {entry.questions && entry.questions.length > 0 && (
        <>
          <List dense sx={{ listStyle: "decimal", pl: 3 }}>
            {entry.questions.map((q, i) => (
              <ListItem key={i} sx={{ display: "list-item", py: 0.25 }}>
                <Typography variant="body2">{q}</Typography>
              </ListItem>
            ))}
          </List>
          <Typography variant="caption" color="text.secondary">
            Answer by number, in any order. Skip any and the assistant uses the default it suggests.
          </Typography>
        </>
      )}
    </Box>
  );
}

function FromAssistant({ children }: { children: ReactNode }) {
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
      <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "secondary.main" }} aria-hidden>
        AI
      </Avatar>
      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
        <Typography variant="caption" color="text.secondary">
          Assistant
        </Typography>
        {children}
      </Box>
    </Stack>
  );
}

/**
 * Step 0: describe the study in words. The assistant drafts it, the draft is
 * applied to the store at once (so the builder's controls show it), and the
 * study in the store goes with every message, so later turns refine what
 * the user sees, manual edits included. Nothing runs from here.
 */
export function ChatPanel() {
  const client = useApi();
  const chat = useStudyStore((s) => s.chat);
  const sendChat = useStudyStore((s) => s.sendChat);
  const resetChat = useStudyStore((s) => s.resetChat);
  const [text, setText] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const started = chat.messages.length > 0 || chat.busy;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [chat.messages.length, chat.busy]);

  async function send(message: string) {
    if (!message.trim() || chat.busy) return;
    const before = chat.messages.length;
    setText("");
    await sendChat(message, client);
    // A failed send takes the message back; put it in the box to send again.
    if (useStudyStore.getState().chat.messages.length === before) setText(message);
    input.current?.focus();
  }

  return (
    <Stack spacing={2}>
      {!started && (
        <Box>
          <Typography variant="h1">What do you want to find out?</Typography>
          <Typography color="text.secondary">
            Describe the study in plain words: which programme, which outcome, over what time. The
            assistant asks about anything missing, drafts the study into the builder, and you review
            it before anything runs.
          </Typography>
        </Box>
      )}
      {started && (
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
          <Typography variant="h2">Conversation</Typography>
          <Button
            size="small"
            onClick={() => {
              setConfirmReset(true);
            }}
          >
            Start over
          </Button>
        </Stack>
      )}

      <Stack spacing={2} component="ol" sx={{ p: 0, m: 0, listStyle: "none" }} aria-live="polite">
        {chat.messages.map((m, i) =>
          m.role === "user" ? (
            <Box component="li" key={i} sx={{ display: "flex", justifyContent: "flex-end" }}>
              <Paper
                variant="outlined"
                sx={{
                  px: 2,
                  py: 1,
                  maxWidth: "80%",
                  bgcolor: "action.hover",
                  whiteSpace: "pre-wrap",
                }}
              >
                <Typography variant="body2">{m.content}</Typography>
              </Paper>
            </Box>
          ) : (
            <Box component="li" key={i}>
              <FromAssistant>
                <AssistantMessage entry={m} />
              </FromAssistant>
            </Box>
          ),
        )}
        {chat.busy && (
          <Box component="li">
            <FromAssistant>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <CircularProgress size={16} />
                <Typography variant="body2">Thinking…</Typography>
              </Stack>
            </FromAssistant>
          </Box>
        )}
        {chat.error && (
          <Box component="li">
            <Alert severity="error" role="alert">
              <AlertTitle>Could not reach the assistant</AlertTitle>
              {chat.error}
            </Alert>
          </Box>
        )}
        {chat.hasDraft && !chat.busy && (
          <Box component="li">
            <DraftCard
              onAskChange={() => {
                input.current?.focus();
              }}
            />
          </Box>
        )}
      </Stack>
      <div ref={end} />

      <Card>
        <CardContent>
          <Box
            component="form"
            onSubmit={(e) => {
              e.preventDefault();
              void send(text);
            }}
          >
            <TextField
              inputRef={input}
              fullWidth
              multiline
              minRows={3}
              label="Message"
              value={text}
              placeholder={
                started
                  ? 'Answer, or ask for a change, e.g. "use 6 months instead of 12"'
                  : "Describe your study, e.g. which programme, which outcome, over what time…"
              }
              slotProps={{ htmlInput: { maxLength: 20000 } }}
              onChange={(e) => {
                setText(e.target.value);
              }}
              onKeyDown={(e) => {
                // Enter sends, Shift+Enter starts a new line.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(text);
                }
              }}
            />
            <Stack
              direction="row"
              sx={{ justifyContent: "space-between", alignItems: "center", mt: 1 }}
            >
              <Typography variant="caption" color="text.secondary">
                {started
                  ? "The assistant drafts. You decide what runs."
                  : "Enter to send · Shift+Enter for a new line"}
              </Typography>
              <Button type="submit" variant="contained" disabled={chat.busy}>
                Send
              </Button>
            </Stack>
          </Box>
        </CardContent>
      </Card>

      {!started && (
        <Box>
          <Typography variant="overline" color="text.secondary">
            Try an example
          </Typography>
          <Stack spacing={1} sx={{ alignItems: "flex-start" }}>
            {EXAMPLES.map((example) => (
              <Chip
                key={example}
                label={example}
                variant="outlined"
                onClick={() => {
                  void send(example);
                }}
                sx={{ height: "auto", py: 0.75, "& .MuiChip-label": { whiteSpace: "normal" } }}
              />
            ))}
          </Stack>
        </Box>
      )}

      <ConfirmDialog
        open={confirmReset}
        title="Start the conversation over?"
        message="The conversation is cleared. The study in the builder stays as it is."
        confirmLabel="Start over"
        onConfirm={resetChat}
        onClose={() => {
          setConfirmReset(false);
        }}
      />
    </Stack>
  );
}
