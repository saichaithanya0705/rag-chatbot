import styles from "@/shared/ui/status-pill/status-pill.module.css";
import { cn } from "@/shared/lib/cn";

type Tone = "neutral" | "accent" | "warning" | "success";

interface StatusPillProps {
  className?: string;
  label: string;
  tone: Tone;
}

export function StatusPill({ className, label, tone }: StatusPillProps) {
  return <span className={cn(styles.pill, styles[tone], className)}>{label}</span>;
}
