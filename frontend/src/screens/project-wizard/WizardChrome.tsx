import type { ReactNode } from "react";
import { ArrowLeft, Check, Sparkles, Trash2 } from "lucide-react";
import { Link } from "react-router";
import { Button } from "../../components/ui";

interface WizardChromeProps {
  trackLabel: string | null;
  step: number;
  maxStep: number;
  stepLabels: string[];
  onStepChange: (step: number) => void;
  onSaveAndExit?: () => void;
  onDiscard?: () => void;
  onBack?: () => void;
  children: ReactNode;
}

/** Общий каркас сохраняет baseline Мастера, а содержимое шагов остаётся у веток. */
export function WizardChrome({
  trackLabel,
  step,
  maxStep,
  stepLabels,
  onStepChange,
  onSaveAndExit,
  onDiscard,
  onBack,
  children,
}: WizardChromeProps) {
  const isLanding = step === 0;
  const progress = stepLabels.length > 1
    ? Math.min(100, Math.max(0, ((step - 1) / (stepLabels.length - 1)) * 100))
    : 0;

  return (
    <div className="project-wizard">
      <header className="wizard-topbar">
        {onBack ? (
          <button type="button" className="wizard-back-projects" onClick={onBack}>
            <ArrowLeft size={16} aria-hidden="true" />
            <span>К выбору</span>
          </button>
        ) : onSaveAndExit ? (
          <button type="button" className="wizard-back-projects" onClick={onSaveAndExit}>
            <ArrowLeft size={16} aria-hidden="true" />
            <span>Сохранить и выйти</span>
          </button>
        ) : (
          <Link className="wizard-back-projects" to="/projects">
            <ArrowLeft size={16} aria-hidden="true" />
            <span>К проектам</span>
          </Link>
        )}
        <span className="wizard-brand"><Sparkles size={17} aria-hidden="true" />Tentex</span>
        <div className="wizard-topbar-actions">
          <span className="wizard-step-caption">
            {trackLabel && !isLanding ? `${trackLabel} — шаг ${step} из ${stepLabels.length}` : "Мастер проектов"}
          </span>
          {onDiscard && (
            <Button variant="ghost" className="wizard-discard" onClick={onDiscard}>
              <Trash2 size={15} aria-hidden="true" />Удалить черновик
            </Button>
          )}
        </div>
      </header>

      {!isLanding && (
        <nav className="wizard-progress" aria-label="Шаги создания проекта">
          <span className="wizard-progress-line" aria-hidden="true"><i style={{ width: `${progress}%` }} /></span>
          {stepLabels.map((label, index) => {
            const itemStep = index + 1;
            const available = itemStep <= maxStep;
            return (
              <button
                type="button"
                key={label}
                className={`${itemStep === step ? "is-current" : ""} ${itemStep < step ? "is-complete" : ""}`.trim()}
                disabled={!available}
                aria-current={itemStep === step ? "step" : undefined}
                aria-label={`${itemStep}. ${label}`}
                onClick={() => onStepChange(itemStep)}
              >
                <span>{itemStep < step ? <Check size={13} strokeWidth={3} /> : itemStep}</span>
                <small>{label}</small>
              </button>
            );
          })}
        </nav>
      )}

      <main className={`wizard-main ${isLanding ? "is-landing" : ""}`.trim()}>
        <div className="wizard-step" key={step}>{children}</div>
      </main>
    </div>
  );
}
