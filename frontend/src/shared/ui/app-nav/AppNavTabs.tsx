import { useLocation, useNavigate } from "react-router-dom";
import { cn } from "@/shared/lib/cn";
import styles from "./app-nav-tabs.module.css";

interface AppNavTabsProps {
  className?: string;
}

export function AppNavTabs({ className }: AppNavTabsProps) {
  const location = useLocation();
  const navigate = useNavigate();

  const currentPath = location.pathname;

  const tabs = [
    {
      id: "chat",
      path: "/chat",
      label: "Chat",
      icon: (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      ),
    },
    {
      id: "pipeline",
      path: "/pipeline",
      label: "Pipeline",
      icon: (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      ),
    },
    {
      id: "knowledge-graph",
      path: "/knowledge-graph",
      label: "Graph",
      icon: (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          <circle cx="18" cy="5" r="3" />
          <circle cx="6" cy="12" r="3" />
          <circle cx="18" cy="19" r="3" />
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
          <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
        </svg>
      ),
    },
  ];

  return (
    <nav className={cn(styles.navTabs, className)} aria-label="Main application sections">
      {tabs.map((tab) => {
        const isActive = currentPath === tab.path || (tab.path === "/chat" && currentPath === "/");

        return (
          <button
            key={tab.id}
            className={cn(styles.tabBtn, isActive && styles.tabBtnActive)}
            onClick={() => void navigate(tab.path)}
            type="button"
            role="tab"
            aria-selected={isActive}
          >
            <span className={styles.tabIcon}>{tab.icon}</span>
            <span className={styles.tabLabel}>{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
