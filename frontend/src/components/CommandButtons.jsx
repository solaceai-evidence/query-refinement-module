import './CommandButtons.css';

const CommandButtons = ({ onCommand, disabled }) => {
    const commands = [
        {
            command: '/status',
            label: 'Status',
            hint: 'View progress summary',
            icon: '📊',
            category: 'info'
        },
        {
            command: '/steps',
            label: 'Steps',
            hint: 'List all refinement steps',
            icon: '📋',
            category: 'info'
        },
        {
            command: '/help',
            label: 'Help',
            hint: 'Show available commands',
            icon: '❓',
            category: 'info'
        },
        {
            command: '/skip',
            label: 'Skip',
            hint: 'Skip current question',
            icon: '⏭️',
            category: 'control'
        },
        {
            command: '/done',
            label: 'Done',
            hint: 'Mark current step complete',
            icon: '✅',
            category: 'control'
        },
        {
            command: '/back',
            label: 'Back',
            hint: 'Go to previous question',
            icon: '◀️',
            category: 'navigation'
        },
        {
            command: '/restart',
            label: 'Restart',
            hint: 'Start refinement from beginning',
            icon: '🔄',
            category: 'navigation'
        },
        {
            command: '/submit',
            label: 'Submit',
            hint: 'Finish refinement now',
            icon: '🏁',
            category: 'control'
        }
    ];

    const handleGoto = () => {
        const stepNum = prompt('Enter step number to jump to:');
        if (stepNum && !isNaN(stepNum)) {
            onCommand(`/goto ${stepNum}`);
        }
    };

    return (
        <div className="command-buttons">
            <div className="command-label">Quick Actions:</div>

            <div className="command-sections">
                <div className="command-section">
                    <div className="section-label">Info</div>
                    <div className="command-button-group">
                        {commands.filter(cmd => cmd.category === 'info').map((cmd) => (
                            <button
                                key={cmd.command}
                                className="command-btn"
                                onClick={() => onCommand(cmd.command)}
                                disabled={disabled}
                                title={cmd.hint}
                            >
                                <span className="command-icon">{cmd.icon}</span>
                                <span className="command-text">{cmd.label}</span>
                            </button>
                        ))}
                    </div>
                </div>

                <div className="command-section">
                    <div className="section-label">Control</div>
                    <div className="command-button-group">
                        {commands.filter(cmd => cmd.category === 'control').map((cmd) => (
                            <button
                                key={cmd.command}
                                className="command-btn"
                                onClick={() => onCommand(cmd.command)}
                                disabled={disabled}
                                title={cmd.hint}
                            >
                                <span className="command-icon">{cmd.icon}</span>
                                <span className="command-text">{cmd.label}</span>
                            </button>
                        ))}
                    </div>
                </div>

                <div className="command-section">
                    <div className="section-label">Navigation</div>
                    <div className="command-button-group">
                        {commands.filter(cmd => cmd.category === 'navigation').map((cmd) => (
                            <button
                                key={cmd.command}
                                className="command-btn"
                                onClick={() => onCommand(cmd.command)}
                                disabled={disabled}
                                title={cmd.hint}
                            >
                                <span className="command-icon">{cmd.icon}</span>
                                <span className="command-text">{cmd.label}</span>
                            </button>
                        ))}
                        <button
                            className="command-btn"
                            onClick={handleGoto}
                            disabled={disabled}
                            title="Jump to specific step"
                        >
                            <span className="command-icon">🎯</span>
                            <span className="command-text">Go To</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CommandButtons;
