import { useEffect } from "react";
import styles from "./knowledge-graph-explorer.module.css";

interface GraphGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function GraphGuideModal({ isOpen, onClose }: GraphGuideModalProps) {
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      aria-labelledby="guide-modal-title"
      aria-modal="true"
      className={styles.modalBackdrop}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
    >
      <div className={styles.guideModalCard}>
        <div className={styles.guideModalHeader}>
          <div className={styles.guideModalTitleGroup}>
            <div className={styles.guideBadge}>3D Visuals &amp; Explorer Guide</div>
            <h2 className={styles.guideModalTitle} id="guide-modal-title">
              How to Navigate the Knowledge Constellation
            </h2>
          </div>
          <button
            aria-label="Close guide"
            className={styles.guideCloseButton}
            onClick={onClose}
            type="button"
          >
            ✕
          </button>
        </div>

        <div className={styles.guideModalBody}>
          <div className={styles.guideGrid}>
            <div className={styles.guideCard}>
              <div className={styles.guideCardIcon}>🪐</div>
              <h3 className={styles.guideCardTitle}>Topic Spheres (Nodes)</h3>
              <p className={styles.guideCardText}>
                Each glowing 3D sphere represents a key subject extracted from your indexed documents.
              </p>
              <ul className={styles.guideBulletList}>
                <li><strong>Sphere Size:</strong> Larger spheres contain more indexed chunk excerpts.</li>
                <li><strong>Glow &amp; Color:</strong> Blue marks single-document topics, lilac marks cross-document topics, and amber marks isolated topics.</li>
                <li><strong>Selection:</strong> Click any sphere to isolate its direct links and view citations.</li>
              </ul>
            </div>

            <div className={styles.guideCard}>
              <div className={styles.guideCardIcon}>⚡</div>
              <h3 className={styles.guideCardTitle}>Relationship Beams (Edges)</h3>
              <p className={styles.guideCardText}>
                Curved links connect topics that share conceptual overlap or cite similar source passages.
              </p>
              <ul className={styles.guideBulletList}>
                <li><strong>Beam Thickness:</strong> Thicker lines denote higher semantic similarity and co-occurrence.</li>
                <li><strong>Inspection:</strong> Click any beam to view correlation breakdowns (page overlap &amp; semantic score).</li>
                <li><strong>Filtering:</strong> Use the <em>Min strength</em> slider above to remove weak ties.</li>
              </ul>
            </div>

            <div className={styles.guideCard}>
              <div className={styles.guideCardIcon}>🧭</div>
              <h3 className={styles.guideCardTitle}>3D Orbit Navigation</h3>
              <p className={styles.guideCardText}>
                Fly around your knowledge base in full 360° space using intuitive mouse and touch gestures:
              </p>
              <div className={styles.guideShortcutGrid}>
                <div className={styles.shortcutRow}>
                  <kbd>Left Click + Drag</kbd>
                  <span>Rotate &amp; orbit around topics in 3D</span>
                </div>
                <div className={styles.shortcutRow}>
                  <kbd>Right Click + Drag</kbd>
                  <span>Pan / translate camera in 3D space</span>
                </div>
                <div className={styles.shortcutRow}>
                  <kbd>Scroll Wheel / Pinch</kbd>
                  <span>Smooth zoom in and out</span>
                </div>
                <div className={styles.shortcutRow}>
                  <kbd>Double Click Node</kbd>
                  <span>Instantly focus camera on topic</span>
                </div>
              </div>
            </div>

            <div className={styles.guideCard}>
              <div className={styles.guideCardIcon}>💬</div>
              <h3 className={styles.guideCardTitle}>Grounded Research</h3>
              <p className={styles.guideCardText}>
                Seamlessly transition from exploration into active reasoning with the integrated AI chat:
              </p>
              <ul className={styles.guideBulletList}>
                <li>
                  <strong>Direct Chat:</strong> Click <em>&quot;Ask chat about this topic ➔&quot;</em> in the inspector to prompt the AI with this exact topic.
                </li>
                <li>
                  <strong>2D / 3D Views:</strong> Toggle between the <em>🪐 3D Constellation</em> (immersive depth) and <em>🗺️ 2D Map</em> (compact schematic) at any time.
                </li>
                <li>
                  <strong>Hop Depth:</strong> Expand or restrict the visible neighborhood to 1 or 2 hops around the selected topic.
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div className={styles.guideModalFooter}>
          <span className={styles.guideFooterHint}>
            💡 You can reopen this guide anytime by clicking <strong>Guide</strong> in the toolbar or 3D canvas.
          </span>
          <button className={styles.guideSubmitButton} onClick={onClose} type="button">
            Got it, explore constellation
          </button>
        </div>
      </div>
    </div>
  );
}
