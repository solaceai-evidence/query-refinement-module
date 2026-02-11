/**
 * User command definitions
 * These must match the backend UserCommand enum
 * @module constants/commands
 */

/**
 * Valid user command strings
 * @readonly
 * @enum {string}
 */
export const USER_COMMANDS = {
    // Navigation commands
    BACK: '/back',
    PREV: '/prev',
    PREVIOUS: '/previous',
    RESTART: '/restart',

    // Control commands
    SKIP: '/skip',
    DONE: '/done',
    CLEAR: '/clear',
    SUBMIT: '/submit',
    END: '/end',

    // Information commands
    STATUS: '/status',
    STEPS: '/steps',
    HELP: '/help'
};

/**
 * All valid command strings as an array
 * @type {string[]}
 */
export const ALL_COMMANDS = Object.values(USER_COMMANDS);

/**
 * Commands that accept arguments
 * @type {string[]}
 */
export const COMMANDS_WITH_ARGS = [];

/**
 * Command aliases (multiple commands that do the same thing)
 * @type {Object.<string, string[]>}
 */
export const COMMAND_ALIASES = {
    back: [USER_COMMANDS.BACK, USER_COMMANDS.PREV, USER_COMMANDS.PREVIOUS],
    submit: [USER_COMMANDS.SUBMIT, USER_COMMANDS.END]
};

/**
 * Command metadata for UI display
 * @type {Object.<string, {label: string, icon: string, hint: string, category: string, behavior: string}>}
 */
export const COMMAND_METADATA = {
    [USER_COMMANDS.STATUS]: {
        label: 'View Progress',
        icon: '📊',
        hint: 'Show how many dimensions completed',
        category: 'info',
        behavior: 'informational' // Don't change flow state
    },
    [USER_COMMANDS.STEPS]: {
        label: 'Show All Steps',
        icon: '📋',
        hint: 'List all dimensions with status',
        category: 'info',
        behavior: 'informational' // Don't change flow state
    },
    [USER_COMMANDS.HELP]: {
        label: 'Help',
        icon: '❓',
        hint: 'Show all available commands',
        category: 'info',
        behavior: 'informational' // Don't change flow state
    },
    [USER_COMMANDS.SKIP]: {
        label: 'Skip This Dimension',
        icon: '⏭️',
        hint: 'Skip without providing details (moves to next)',
        category: 'control',
        behavior: 'navigation' // Changes current question
    },
    [USER_COMMANDS.DONE]: {
        label: 'Dimension Complete',
        icon: '✅',
        hint: 'Finish this dimension and move to next',
        category: 'control',
        behavior: 'navigation' // Changes current question
    },
    [USER_COMMANDS.CLEAR]: {
        label: 'Restart Current',
        icon: '🔃',
        hint: 'Clear answers and restart this dimension',
        category: 'control',
        behavior: 'navigation' // Changes current question
    },
    [USER_COMMANDS.BACK]: {
        label: 'Previous Dimension',
        icon: '◀️',
        hint: 'Go back to previous dimension',
        category: 'navigation',
        behavior: 'navigation' // Changes current question
    },
    [USER_COMMANDS.RESTART]: {
        label: 'Start Over',
        icon: '🔄',
        hint: 'Restart from first dimension',
        category: 'navigation',
        behavior: 'navigation' // Changes current question
    },
    [USER_COMMANDS.SUBMIT]: {
        label: 'Finish & Generate',
        icon: '🏁',
        hint: 'Stop refining and generate final query',
        category: 'control',
        behavior: 'terminating' // Ends the flow
    }
};

/**
 * Check if a command is informational (doesn't change flow state)
 * @param {string} command - Command string
 * @returns {boolean} True if command is informational
 */
export function isInformationalCommand(command) {
    const parsed = parseCommand(command);
    if (!parsed) return false;

    const metadata = COMMAND_METADATA[parsed.command];
    return metadata?.behavior === 'informational';
}

/**
 * Check if a string is a valid user command
 * @param {string} input - User input to check
 * @returns {boolean} True if input is a valid command
 */
export function isUserCommand(input) {
    if (!input || typeof input !== 'string') {
        return false;
    }

    const trimmed = input.trim();

    // Check for exact match with simple commands
    if (ALL_COMMANDS.includes(trimmed)) {
        return true;
    }

    // Check for commands with arguments (e.g., "/goto 2")
    for (const cmd of COMMANDS_WITH_ARGS) {
        if (trimmed.startsWith(cmd + ' ') || trimmed === cmd) {
            return true;
        }
    }

    return false;
}

/**
 * Parse command and extract base command and argument
 * @param {string} input - Command string to parse
 * @returns {{command: string, arg: string | null} | null} Parsed command or null if invalid
 */
export function parseCommand(input) {
    if (!isUserCommand(input)) {
        return null;
    }

    const trimmed = input.trim();

    // Check for commands with arguments
    for (const cmd of COMMANDS_WITH_ARGS) {
        if (trimmed.startsWith(cmd + ' ')) {
            const arg = trimmed.substring(cmd.length + 1).trim();
            return { command: cmd, arg: arg || null };
        }
        if (trimmed === cmd) {
            return { command: cmd, arg: null };
        }
    }

    // Simple command without arguments
    return { command: trimmed, arg: null };
}

/**
 * Get the icon for a command type
 * @param {string} commandType - Command type (without /)
 * @returns {string} Emoji icon
 */
export function getCommandIcon(commandType) {
    const cmd = commandType.startsWith('/') ? commandType : `/${commandType}`;
    return COMMAND_METADATA[cmd]?.icon || '⚡';
}

/**
 * Get commands by category
 * @param {'info' | 'control' | 'navigation'} category
 * @returns {Array<{command: string, metadata: Object}>}
 */
export function getCommandsByCategory(category) {
    return Object.entries(COMMAND_METADATA)
        .filter(([_, meta]) => meta.category === category)
        .map(([command, metadata]) => ({ command, metadata }));
}
