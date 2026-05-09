import type { HTMLAttributes } from "react";
import { cn } from "@/shared/lib/cn";
import styles from "@/shared/ui/surface-card/surface-card.module.css";

export function SurfaceCard({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn(styles.card, className)} {...props} />;
}

