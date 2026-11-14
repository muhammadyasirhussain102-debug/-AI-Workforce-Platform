export interface NavItem {
  id: string;
  label: string;
  icon?: string;
  badgeCount?: number;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'leave', label: 'LeaveFlow' },
  { id: 'rag', label: 'Policy Brain (RAG)' },
  { id: 'attendance', label: 'Attendance' },
  { id: 'tickets', label: 'Helpdesk' },
  { id: 'training', label: 'Onboarding (Day 1-3)' },
  { id: 'complaints', label: 'Anonymous Box' },
];

export class NavigationManager {
  private activeTabId: string = 'leave';

  constructor(private onTabChange?: (tabId: string) => void) {}

  public getActiveTab(): string {
    return this.activeTabId;
  }

  public setActiveTab(tabId: string): void {
    const valid = NAV_ITEMS.some((item) => item.id === tabId);
    if (!valid) {
      console.warn(`Tab '${tabId}' not found in registry.`);
      return;
    }

    this.activeTabId = tabId;

    // Update DOM active state
    document.querySelectorAll('.content-panel').forEach((panel) => {
      panel.classList.remove('active');
    });

    document.querySelectorAll('.nav-item').forEach((item) => {
      item.classList.remove('active');
    });

    const activePanel = document.getElementById(`panel-${tabId}`);
    if (activePanel) {
      activePanel.classList.add('active');
    }

    const titleElement = document.getElementById('current-title');
    const matchingItem = NAV_ITEMS.find((item) => item.id === tabId);
    if (titleElement && matchingItem) {
      titleElement.innerText = matchingItem.label;
    }

    if (this.onTabChange) {
      this.onTabChange(tabId);
    }
  }

  public initEventListeners(): void {
    const listElements = document.querySelectorAll('.nav-item');