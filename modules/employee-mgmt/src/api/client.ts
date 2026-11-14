export interface LeaveBalance {
  leave_type: string;
  entitled: number;
  used: number;
  reserved: number;
  available: number;
}

export interface LeaveRequestPayload {
  start_date: string;
  end_date: string;
  half_day?: boolean;
  reason?: string;
}

export interface LeaveRequestResult {
  request_id: string;
  status: string;
  working_days: number;
  check_result: {
    outcome: string;
    detail: string;
  };
}

export interface Citation {
  chunk_id?: string;
  document_title: string;
  version: number;
  section_path: string;
  page: number;
  snippet: string;
}

export interface PolicyAskResponse {
  question: string;
  user_role: string;
  answer_text: string;
  grounded: boolean;
  citations: Citation[];
  route_to_hr: boolean;
  ticket_id?: string;
}

export interface AnonymousComplaintPayload {
  category: string;
  text: string;
}

export interface AnonymousComplaintResult {
  status: string;
  message: string;
  case_code: string;
  secret_key: string;
  created_date: string;
}

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = "http://127.0.0.1:8000/api/v1") {
    this.baseUrl = baseUrl;
  }

  // --- Leave