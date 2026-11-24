export type NavSectionId =
  | "overview"
  | "attendance"
  | "leave"
  | "policies"
  | "tickets"
  | "training"
  | "complaints";

export type UserRole = "employee" | "manager" | "hr" | "admin";

export interface NavItem {
  readonly id: NavSectionId;
  readonly label: string;
  readonly path: string;
  readonly description: string;
  readonly allowedRoles: readonly UserRole[];
  readonly isAnonymousSafe?: boolean;
}

const ALL_ROLES: readonly UserRole[] = Object.freeze([
  "employee",
  "manager",
  "hr",
  "admin",
]);

export const EMPLOYEE_MGMT_NAV: readonly NavItem[] = Object.freeze([
  Object.freeze({
    id: "overview",
    label: "Overview",
    path: "/employee-mgmt",
    description: "Employee Management workspace summary and quick status.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "attendance",
    label: "Face ID Attendance",
    path: "/employee-mgmt/attendance",
    description: "Biometric check-in, check-out, and attendance lock records.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "leave",
    label: "LeaveFlow",
    path: "/employee-mgmt/leave",
    description: "Leave requests, code-calculated balances, and approvals.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "policies",
    label: "Policy Brain",
    path: "/employee-mgmt/policies",
    description: "Search company policies with citation-backed answers.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "tickets",
    label: "IT Support",
    path: "/employee-mgmt/tickets",
    description: "Submit and track internal IT and workplace support tickets.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "training",
    label: "Training & Quizzes",
    path: "/employee-mgmt/training",
    description: "Assigned training plans, modules, and quiz completion.",
    allowedRoles: ALL_ROLES,
  }),
  Object.freeze({
    id: "complaints",
    label: "Anonymous Box",
    path: "/employee-mgmt/complaints",
    description: "Privacy-preserving anonymous complaint submission and status.",
    allowedRoles: ALL_ROLES,
    isAnonymousSafe: true,
  }),
]);

export function getNavItemById(id: string): NavItem | undefined {
  const normalizedId = id.trim().toLowerCase();
  if (!normalizedId) {
    return undefined;
  }
  return EMPLOYEE_MGMT_NAV.find((item) => item.id === normalizedId);
}

export function getNavItemByPath(path: string): NavItem | undefined {
  const normalizedPath = path.trim().replace(/\/+$/, "") || "/";
  return EMPLOYEE_MGMT_NAV.find((item) => item.path === normalizedPath);
}

export function getVisibleNavItems(role?: UserRole): readonly NavItem[] {
  if (!role) {
    return EMPLOYEE_MGMT_NAV;
  }
  return EMPLOYEE_MGMT_NAV.filter((item) => item.allowedRoles.includes(role));
}