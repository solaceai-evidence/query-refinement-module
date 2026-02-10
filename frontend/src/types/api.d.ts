/**
 * Type definitions for API requests and responses
 * These types provide IntelliSense and validation in JavaScript files via JSDoc
 */

// ============================================================
// Core API Response Types
// ============================================================

export interface NextPrompt {
    aspect_id: string;
    aspect_name: string;
    question: string;
    description: string;
}

export interface StepSummary {
    completed_steps: number;
    total_steps: number;
    pending_steps: number;
    current_aspect?: string;
    current_step?: number;
}

export interface StepListItem {
    aspect_name: string;
    aspect_id: string;
    is_complete: boolean;
    needs_review: boolean;
    was_skipped: boolean;
    follow_up_count: number;
    status: 'completed' | 'needs review' | 'active' | 'not started';
    is_active: boolean;
}

export interface CommandResult {
    type: string;
    message: string;
    success: boolean;
    step_summary?: StepSummary;
    step_list?: StepListItem[];
    invalidated_aspects?: string[];
    synthesis_ready?: boolean;
    force_required?: boolean;
}

// ============================================================
// Refinement API - Start
// ============================================================

export interface StartRefinementRequest {
    original_query: string;
    framework_name: string;
}

export interface StartRefinementResponse {
    session_id: number;
    query_id: number;
    summary: {
        aspects: Array<{
            aspect_name: string;
            status: string;
        }>;
        [key: string]: any;
    };
    next_prompt: NextPrompt | null;
    ready_for_synthesis: boolean;
}

// ============================================================
// Refinement API - Continue
// ============================================================

export interface SubmitAnswerRequest {
    answer: string;
    force?: boolean;
}

export interface SubmitAnswerResponse {
    refinement_step_id: number;
    followup_id: number;
    is_complete: boolean;
    next_prompt: NextPrompt | null;
    ready_for_synthesis: boolean;
}

export interface CommandResponse {
    command_type: string;
    success: boolean;
    message: string;
    next_prompt: NextPrompt | null;
    invalidated_aspects?: string[];
    synthesis_ready?: boolean;
    step_summary?: StepSummary;
    step_list?: StepListItem[];
    force_required?: boolean;
}

export type ContinueRefinementResponse = SubmitAnswerResponse | CommandResponse;

// ============================================================
// Refinement API - Status
// ============================================================

export interface AspectSummary {
    aspect_name: string;
    is_complete: boolean;
    needs_review?: boolean;
    was_skipped?: boolean;
}

export interface GetRefinementStatusResponse {
    query_id: number;
    original_query: string;
    refined_query: string | null;
    is_complete: boolean;
    current_aspect: string | null;
    aspects_summary: {
        aspects: AspectSummary[];
        [key: string]: any;
    };
}

// ============================================================
// Refinement API - Synthesis
// ============================================================

export interface SynthesizeQueryRequest {
    query_id: number;
}

export interface SynthesizeQueryResponse {
    query_id: number;
    integrated_statement: string;
    used_llm: boolean;
    structured_output?: {
        dimensions_specifications?: { [key: string]: any };
        search_optimized?: {
            semantic?: string;
            keyword?: {
                structured?: string;
                phrases?: string[];
                terms?: {
                    required?: string[];
                    optional?: string[];
                    excluded?: string[];
                };
            };
        };
        search_filters?: {
            publication_years?: string;
            venues?: string[];
            authors?: string[];
            publication_types?: string[];
            fields_of_study?: string[];
        };
        terminology?: {
            synonyms?: { [key: string]: string[] };
            colloquial?: string[];
        };
    } | null;
    metadata?: {
        [key: string]: any;
    };
}

// ============================================================
// Conversation History Types
// ============================================================

export interface HistoryItemBase {
    type: 'query' | 'question' | 'answer' | 'command';
    content: string;
    timestamp: string;
    aspectId?: string;
    aspectName?: string;
}

export interface QueryHistoryItem extends HistoryItemBase {
    type: 'query';
}

export interface QuestionHistoryItem extends HistoryItemBase {
    type: 'question';
    aspectId: string;
    aspectName: string;
}

export interface AnswerHistoryItem extends HistoryItemBase {
    type: 'answer';
    aspectId: string;
}

export interface CommandHistoryItem extends HistoryItemBase {
    type: 'command';
    aspectId?: string;
    result?: CommandResult;
}

export type ConversationHistoryItem =
    | QueryHistoryItem
    | QuestionHistoryItem
    | AnswerHistoryItem
    | CommandHistoryItem;

// ============================================================
// Service Method Types
// ============================================================

export interface RefinementService {
    getFrameworks(): Promise<string[]>;
    startRefinement(frameworkName: string, initialQuery: string): Promise<StartRefinementResponse>;
    continueRefinement(sessionId: number, queryId: number, userResponse: string): Promise<ContinueRefinementResponse>;
    getSynthesis(queryId: number): Promise<SynthesizeQueryResponse>;
    getQuery(queryId: number): Promise<any>;
    getStatus(queryId: number): Promise<GetRefinementStatusResponse>;
    listQueries(skip?: number, limit?: number): Promise<any[]>;
    submitFeedback(queryId: number, rating: number, comments?: string): Promise<any>;
}

// ============================================================
// Component Props Types
// ============================================================

export interface CommandButtonsProps {
    onCommand: (command: string) => void | Promise<void>;
    disabled: boolean;
}

export interface CommandHistoryItemProps {
    command: string;
    result?: CommandResult;
}

export interface QuestionRendererProps {
    question: string;
    onAnswer: (answer: string) => void | Promise<void>;
    loading: boolean;
}

export interface AspectStatusPanelProps {
    aspects: AspectSummary[];
}

export interface SynthesisResultProps {
    queryId: number;
    synthesis: SynthesizeQueryResponse;
}

export interface FrameworkSelectorProps {
    onSelect: (framework: string) => void;
}

// ============================================================
// Utility Type Guards
// ============================================================

export function isCommandResponse(response: ContinueRefinementResponse): response is CommandResponse;
export function isSubmitAnswerResponse(response: ContinueRefinementResponse): response is SubmitAnswerResponse;
