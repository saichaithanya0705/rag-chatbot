import { cn } from "@/shared/lib/cn";
import styles from "@/shared/ui/citation-chip/citation-chip.module.css";

type CitationChipVariant = "pdf" | "web";

interface CitationChipProps {
  className?: string;
  href?: string;
  label: string;
  onClick?: () => void;
  title?: string;
  variant?: CitationChipVariant;
}

function PdfIcon() {
  return (
    <svg fill="none" height="12" viewBox="0 0 16 16" width="12">
      <rect height="14" rx="1.5" stroke="currentColor" strokeWidth="1.2" width="10" x="3" y="1" />
      <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeLinecap="round" strokeWidth="1" />
    </svg>
  );
}

function WebIcon() {
  return (
    <svg fill="none" height="12" viewBox="0 0 16 16" width="12">
      <path
        d="M6.5 9.5L9.5 6.5M5 11H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h5a2 2 0 0 1 2 2v1M7 14h5a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.1"
      />
    </svg>
  );
}

export function CitationChip({
  className,
  href,
  label,
  onClick,
  title,
  variant = "pdf",
}: CitationChipProps) {
  const content = (
    <>
      {variant === "pdf" ? <PdfIcon /> : <WebIcon />}
      <span>{label}</span>
    </>
  );

  if (href) {
    return (
      <a
        className={cn(styles.chip, styles[variant], className)}
        href={href}
        rel="noreferrer"
        target="_blank"
        title={title ?? label}
      >
        {content}
      </a>
    );
  }

  return (
    <button
      className={cn(styles.chip, styles[variant], className)}
      onClick={onClick}
      title={title ?? label}
      type="button"
    >
      {content}
    </button>
  );
}
