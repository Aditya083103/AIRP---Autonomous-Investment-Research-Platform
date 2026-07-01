// frontend/src/components/ui/index.ts
// Barrel export for the AIRP design system (T-054). Lets the rest of the
// app write `import { Button, Card, Badge } from "@/components/ui"`
// instead of one import line per component file.

export { Badge, type BadgeProps, type BadgeTone } from "@/components/ui/Badge";
export {
  Button,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
} from "@/components/ui/Button";
export {
  Card,
  type CardProps,
  type CardHeaderProps,
  type CardTitleProps,
  type CardDescriptionProps,
  type CardFooterProps,
} from "@/components/ui/Card";
export { Input, type InputProps } from "@/components/ui/Input";
export { Modal, type ModalProps, type ModalSize } from "@/components/ui/Modal";
export { ProgressBar, type ProgressBarProps } from "@/components/ui/ProgressBar";
export { Spinner, type SpinnerProps, type SpinnerSize } from "@/components/ui/Spinner";
export { Tooltip, type TooltipProps, type TooltipPlacement } from "@/components/ui/Tooltip";
