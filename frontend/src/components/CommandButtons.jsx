import './CommandButtons.css';
import { USER_COMMANDS, COMMAND_METADATA, getCommandsByCategory } from '../constants/commands';

/**
 * @typedef {import('../types/api').CommandButtonsProps} CommandButtonsProps
 */

/**
 * Quick action buttons for user commands
 * @param {CommandButtonsProps} props
 * @returns {JSX.Element}
 */
const CommandButtons = ({ onCommand, disabled }) => {
    // Build command list from centralized definitions
    const infoCommands = getCommandsByCategory('info');
    const controlCommands = getCommandsByCategory('control').filter(
        ({ command }) => command !== USER_COMMANDS.SUBMIT // Filter out submit, we'll add it separately
    );
    const navigationCommands = getCommandsByCategory('navigation').filter(
        ({ command }) => command !== USER_COMMANDS.GOTO // Filter out goto, handled separately
    );

    // Add submit command explicitly
    controlCommands.push({
        command: USER_COMMANDS.SUBMIT,
        metadata: COMMAND_METADATA[USER_COMMANDS.SUBMIT]
    });

    const handleGoto = () => {
        const stepNum = prompt('Enter step number to jump to:');
        if (stepNum && !isNaN(stepNum)) {
            onCommand(`${USER_COMMANDS.GOTO} ${stepNum}`);
        }
    };

    return (
        <div className="command-buttons">
            <div className="command-label">Quick Actions:</div>

            <div className="command-sections">
                <div className="command-section">
                    <div className="section-label">Info</div>
                    <div className="command-button-group">
                        {infoCommands.map(({ command, metadata }) => (
                            <button
                                key={command}
                                className="command-btn"
                                onClick={() => onCommand(command)}
                                disabled={disabled}
                                title={metadata.hint}
                            >
                                <span className="command-icon">{metadata.icon}</span>
                                <span className="command-text">{metadata.label}</span>
                            </button>
                        ))}
                    </div>
                </div>

                <div className="command-section">
                    <div className="section-label">Control</div>
                    <div className="command-button-group">
                        {controlCommands.map(({ command, metadata }) => (
                            <button
                                key={command}
                                className="command-btn"
                                onClick={() => onCommand(command)}
                                disabled={disabled}
                                title={metadata.hint}
                            >
                                <span className="command-icon">{metadata.icon}</span>
                                <span className="command-text">{metadata.label}</span>
                            </button>
                        ))}
                    </div>
                </div>

                <div className="command-section">
                    <div className="section-label">Navigation</div>
                    <div className="command-button-group">
                        {navigationCommands.map(({ command, metadata }) => (
                            <button
                                key={command}
                                className="command-btn"
                                onClick={() => onCommand(command)}
                                disabled={disabled}
                                title={metadata.hint}
                            >
                                <span className="command-icon">{metadata.icon}</span>
                                <span className="command-text">{metadata.label}</span>
                            </button>
                        ))}
                        <button
                            className="command-btn"
                            onClick={handleGoto}
                            disabled={disabled}
                            title={COMMAND_METADATA[USER_COMMANDS.GOTO].hint}
                        >
                            <span className="command-icon">{COMMAND_METADATA[USER_COMMANDS.GOTO].icon}</span>
                            <span className="command-text">{COMMAND_METADATA[USER_COMMANDS.GOTO].label}</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CommandButtons;
