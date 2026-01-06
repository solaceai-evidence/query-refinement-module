import { useState, useEffect } from 'react';
import { refinementService } from '../services/refinement';
import './FrameworkSelector.css';

const FrameworkSelector = ({ onSelect }) => {
    const [frameworks, setFrameworks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        loadFrameworks();
    }, []);

    const loadFrameworks = async () => {
        try {
            setLoading(true);
            const data = await refinementService.getFrameworks();
            setFrameworks(data.frameworks || []);
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to load frameworks');
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return <div className="framework-loading">Loading frameworks...</div>;
    }

    if (error) {
        return (
            <div className="framework-error">
                <p>{error}</p>
                <button onClick={loadFrameworks} className="btn-retry">Retry</button>
            </div>
        );
    }

    return (
        <div className="framework-selector">
            <h2>Select a Framework</h2>
            <div className="framework-grid">
                {frameworks.map((framework) => (
                    <div
                        key={framework}
                        className="framework-card"
                        onClick={() => onSelect(framework)}
                    >
                        <h3>{framework}</h3>
                        <p>Click to start refinement</p>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default FrameworkSelector;
