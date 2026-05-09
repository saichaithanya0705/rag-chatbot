import type { ElementType, ReactNode } from "react";
import { cn } from "@/shared/lib/cn";
import styles from "@/shared/ui/section-label/section-label.module.css";

interface SectionLabelProps {
  as?: ElementType;
  children: ReactNode;
  className?: string;
}

export function SectionLabel({ as: Component = "span", children, className }: SectionLabelProps) {
  return <Component className={cn(styles.label, className)}>{children}</Component>;
}
