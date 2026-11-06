import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { Fragment, type ReactNode } from "react";

/**
 * The small part of Markdown the assistant writes: paragraphs, "-" / "*" and
 * "1." lists, "#" headings, **bold**, *italic* and `code`. Everything is
 * rendered as React elements, never as HTML, so the text cannot inject markup.
 */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push(
        <Typography key={blocks.length} variant="body2" sx={{ mb: 1 }}>
          {paragraph.map((line, i) => (
            <Fragment key={i}>
              {i > 0 && <br />}
              {inline(line)}
            </Fragment>
          ))}
        </Typography>,
      );
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push(
        <Box
          key={blocks.length}
          component={list.ordered ? "ol" : "ul"}
          sx={{
            mt: 0,
            mb: 1,
            pl: 3,
            listStyle: list.ordered ? "decimal" : "disc",
            "& li": { mb: 0.25 },
          }}
        >
          {list.items.map((item, i) => (
            <Typography key={i} component="li" variant="body2">
              {inline(item)}
            </Typography>
          ))}
        </Box>,
      );
      list = null;
    }
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (line === "") {
      flushParagraph();
      flushList();
    } else if (bullet || numbered) {
      flushParagraph();
      const ordered = numbered !== null;
      const item = (bullet ?? numbered)?.[1] ?? "";
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push(item);
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push(
        <Typography key={blocks.length} variant="subtitle2" sx={{ mb: 0.5 }}>
          {inline(heading[1] ?? "")}
        </Typography>,
      );
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return <>{blocks}</>;
}

/** **bold**, *italic* / _italic_ and `code` inside one line. */
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*)\*|\b_([^_]+)_\b/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const at = match.index;
    if (at > last) parts.push(text.slice(last, at));
    const [, bold, code, star, underscore] = match;
    if (bold !== undefined) {
      parts.push(<strong key={at}>{inline(bold)}</strong>);
    } else if (code !== undefined) {
      parts.push(
        <Box key={at} component="code" sx={{ fontFamily: "monospace", fontSize: "0.9em" }}>
          {code}
        </Box>,
      );
    } else {
      parts.push(<em key={at}>{star ?? underscore}</em>);
    }
    last = at + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
