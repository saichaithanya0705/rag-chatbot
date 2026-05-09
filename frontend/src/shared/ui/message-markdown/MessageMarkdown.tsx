import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageMarkdownProps {
  content: string;
}

const markdownComponents: Components = {
  a({ children, href, ...props }) {
    return (
      <a href={href} rel="noreferrer noopener" target="_blank" {...props}>
        {children}
      </a>
    );
  },
};

export function MessageMarkdown({ content }: MessageMarkdownProps) {
  return (
    <Markdown components={markdownComponents} remarkPlugins={[remarkGfm]}>
      {content}
    </Markdown>
  );
}
