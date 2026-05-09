import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/shared/lib/cn";
import styles from "@/shared/ui/button/button.module.css";

type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  stretch?: boolean;
  iconLeading?: ReactNode;
}

export function Button({
  className,
  children,
  variant = "secondary",
  size = "md",
  stretch = false,
  iconLeading,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        styles.button,
        styles[variant],
        styles[size],
        stretch && styles.stretch,
        className,
      )}
      type={type}
      {...props}
    >
      {iconLeading ? <span className={styles.icon}>{iconLeading}</span> : null}
      <span>{children}</span>
    </button>
  );
}

