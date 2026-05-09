import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/shared/lib/cn";
import styles from "@/shared/ui/icon-button/icon-button.module.css";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode;
  active?: boolean;
  label: string;
}

export function IconButton({
  className,
  icon,
  active = false,
  label,
  type = "button",
  ...props
}: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={cn(styles.button, active && styles.active, className)}
      title={label}
      type={type}
      {...props}
    >
      {icon}
    </button>
  );
}

