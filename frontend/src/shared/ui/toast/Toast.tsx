import styles from "@/shared/ui/toast/toast.module.css";
import { cn } from "@/shared/lib/cn";

interface ToastProps {
  message: string | null;
}

export function Toast({ message }: ToastProps) {
  return (
    <div
      aria-atomic="true"
      aria-live="polite"
      className={cn(styles.toast, message && styles.visible)}
      role="status"
    >
      {message}
    </div>
  );
}
