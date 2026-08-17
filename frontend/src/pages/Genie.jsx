import { useState, useRef, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { sendGenieMessage, getGenieSuggestions, exportGenieCsv } from '../services/api';
import Header from '../components/Header';
import {
  Sparkles, Send, User, Shield, Loader2, Lightbulb, Trash2,
  Database, BarChart3, FlaskConical, ChevronDown, ChevronRight, Download,
} from 'lucide-react';

export default function Genie() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        "Hello! I'm **Genie**, your VST inventory intelligence assistant.\n\n" +
        "I can help with:\n" +
        "- **Stock Advisory** — \"Do we need to order more Spare Parts for December?\"\n" +
        "- **Data Queries** — \"How many SKUs are there per category?\"\n" +
        "- **What-If Scenarios** — \"What if lead time from China increases by 15 days?\"\n\n" +
        "Try one of the suggestions below, or ask me anything!",
      confidence: { level: 'high', tag: 'Welcome' },
      reasoning_trace: null,
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const { data: suggestionsData } = useQuery({
    queryKey: ['genie-suggestions'],
    queryFn: () => getGenieSuggestions().then((r) => r.data),
  });
  const suggestions = suggestionsData?.suggestions || [];

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);
  useEffect(scrollToBottom, [messages, scrollToBottom]);

  const handleSend = useCallback(
    async (text) => {
      const messageText = text || input.trim();
      if (!messageText || isLoading) return;

      setMessages((prev) => [
        ...prev,
        { role: 'user', content: messageText, timestamp: new Date().toISOString() },
      ]);
      setInput('');
      setIsLoading(true);

      try {
        const response = await sendGenieMessage(messageText, conversationId);
        const data = response.data;
        if (!conversationId) setConversationId(data.conversation_id);

        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.response,
            intent: data.intent,
            confidence: data.confidence,
            data_sources: data.data_sources,
            reasoning_trace: data.reasoning_trace,
            data: data.data,
            timestamp: new Date().toISOString(),
          },
        ]);
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content:
              'Sorry, I encountered an error. Please try again.\n\n' +
              '*If the backend is not running, start it with `uvicorn app.main:app --reload`*',
            confidence: { level: 'low', tag: 'Error' },
            reasoning_trace: null,
            timestamp: new Date().toISOString(),
          },
        ]);
      } finally {
        setIsLoading(false);
        inputRef.current?.focus();
      }
    },
    [input, isLoading, conversationId],
  );

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearChat = () => {
    setMessages([
      {
        role: 'assistant',
        content: 'Chat cleared! How can I help you?',
        confidence: { level: 'high', tag: 'System' },
        reasoning_trace: null,
        timestamp: new Date().toISOString(),
      },
    ]);
    setConversationId(null);
  };

  /* ── Markdown renderer (tables, bold, headers, lists) ───────────── */
  const renderMarkdown = (text) => {
    if (!text) return null;
    const lines = text.split('\n');
    const elements = [];
    let inTable = false;
    let tableRows = [];
    let tableKey = 0;

    const processInline = (line) =>
      line
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('|') && line.endsWith('|')) {
        if (!inTable) { inTable = true; tableRows = []; }
        if (!/^\|[-\s|]+\|$/.test(line)) {
          tableRows.push(line.split('|').filter((c) => c.trim()).map((c) => c.trim()));
        }
        continue;
      }
      if (inTable) {
        inTable = false;
        if (tableRows.length > 0) {
          elements.push(
            <div key={`tbl-${tableKey++}`} className="genie-table-wrap">
              <table className="genie-table">
                <thead><tr>{tableRows[0].map((c, j) => <th key={j} dangerouslySetInnerHTML={{ __html: processInline(c) }} />)}</tr></thead>
                <tbody>{tableRows.slice(1).map((row, ri) => <tr key={ri}>{row.map((c, j) => <td key={j} dangerouslySetInnerHTML={{ __html: processInline(c) }} />)}</tr>)}</tbody>
              </table>
            </div>,
          );
        }
        tableRows = [];
      }
      if (line.startsWith('## ')) {
        elements.push(<h3 key={i} className="genie-h3" dangerouslySetInnerHTML={{ __html: processInline(line.slice(3)) }} />);
      } else if (line.startsWith('### ')) {
        elements.push(<h4 key={i} className="genie-h4" dangerouslySetInnerHTML={{ __html: processInline(line.slice(4)) }} />);
      } else if (line.startsWith('- ')) {
        elements.push(<li key={i} className="genie-li" dangerouslySetInnerHTML={{ __html: processInline(line.slice(2)) }} />);
      } else if (line === '') {
        elements.push(<br key={i} />);
      } else {
        elements.push(<p key={i} className="genie-p" dangerouslySetInnerHTML={{ __html: processInline(line) }} />);
      }
    }
    if (inTable && tableRows.length > 0) {
      elements.push(
        <div key={`tbl-${tableKey++}`} className="genie-table-wrap">
          <table className="genie-table">
            <thead><tr>{tableRows[0].map((c, j) => <th key={j} dangerouslySetInnerHTML={{ __html: processInline(c) }} />)}</tr></thead>
            <tbody>{tableRows.slice(1).map((row, ri) => <tr key={ri}>{row.map((c, j) => <td key={j} dangerouslySetInnerHTML={{ __html: processInline(c) }} />)}</tr>)}</tbody>
          </table>
        </div>,
      );
    }
    return elements;
  };

  /* ── Reasoning Trace renderer ───────────────────────────────────── */
  const ReasoningTrace = ({ trace }) => {
    const [expanded, setExpanded] = useState(false);
    if (!trace) return null;

    const hasSql = !!trace.sql;
    const hasAdvisor = !!trace.stock_advisor;
    const hasWhatIf = !!trace.what_if;
    if (!hasSql && !hasAdvisor && !hasWhatIf) return null;

    return (
      <div className="genie-trace">
        <button className="genie-trace-toggle" onClick={() => setExpanded(!expanded)}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span className="genie-trace-toggle-label">Show expert reasoning</span>
        </button>
        {expanded && (
          <div className="genie-trace-body">
            {/* SQL Agent result */}
            {hasSql && (
              <div className="genie-trace-block">
                <div className="genie-trace-header">
                  <Database size={14} />
                  <span>Expert A — SQL Agent</span>
                </div>
                {trace.sql.sql && (
                  <pre className="genie-trace-sql">{trace.sql.sql}</pre>
                )}
                {trace.sql.row_count > 0 && (
                  <p className="genie-trace-meta">{trace.sql.row_count} row(s) returned</p>
                )}
                {trace.sql.error && (
                  <p className="genie-trace-error">{trace.sql.error}</p>
                )}
                {trace.sql.sample && trace.sql.sample.length > 0 && (
                  <div className="genie-table-wrap">
                    <table className="genie-table">
                      <thead>
                        <tr>{Object.keys(trace.sql.sample[0]).map((k) => <th key={k}>{k}</th>)}</tr>
                      </thead>
                      <tbody>
                        {trace.sql.sample.map((row, i) => (
                          <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{String(v ?? '')}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Stock Advisor result */}
            {hasAdvisor && trace.stock_advisor.expert_a && (
              <div className="genie-trace-block">
                <div className="genie-trace-header">
                  <BarChart3 size={14} />
                  <span>Expert A — Current Inventory ({trace.stock_advisor.expert_a.count} SKUs)</span>
                </div>
                {trace.stock_advisor.expert_a.skus && trace.stock_advisor.expert_a.skus.length > 0 && (
                  <div className="genie-table-wrap">
                    <table className="genie-table">
                      <thead>
                        <tr><th>SKU</th><th>Category</th><th>Avg Weekly</th><th>Est. Stock</th><th>Coverage</th></tr>
                      </thead>
                      <tbody>
                        {trace.stock_advisor.expert_a.skus.slice(0, 8).map((s, i) => (
                          <tr key={i}>
                            <td><code>{s.sku_id}</code></td>
                            <td>{s.category}</td>
                            <td>{s.avg_weekly_demand}</td>
                            <td>{s.estimated_stock}</td>
                            <td>{s.coverage_weeks}w</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {hasAdvisor && trace.stock_advisor.expert_b && (
              <div className="genie-trace-block">
                <div className="genie-trace-header">
                  <BarChart3 size={14} />
                  <span>Expert B — Forecast ({trace.stock_advisor.expert_b.month_label})</span>
                </div>
                {trace.stock_advisor.expert_b.skus && trace.stock_advisor.expert_b.skus.length > 0 && (
                  <div className="genie-table-wrap">
                    <table className="genie-table">
                      <thead>
                        <tr><th>SKU</th><th>Monthly Demand</th><th>Source</th></tr>
                      </thead>
                      <tbody>
                        {trace.stock_advisor.expert_b.skus.slice(0, 8).map((d, i) => (
                          <tr key={i}>
                            <td><code>{d.sku_id}</code></td>
                            <td>{d.monthly_demand}</td>
                            <td>{d.source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {hasAdvisor && trace.stock_advisor.math && (
              <div className="genie-trace-block">
                <div className="genie-trace-header">
                  <span>Math — Shortfall Analysis</span>
                </div>
                <p className="genie-trace-meta">
                  {trace.stock_advisor.math.skus_needing_reorder} SKUs needing reorder &middot;{' '}
                  {trace.stock_advisor.math.total_shortfall_units} unit total shortfall
                </p>
                {trace.stock_advisor.math.skus && trace.stock_advisor.math.skus.length > 0 && (
                  <div className="genie-table-wrap genie-table-scroll">
                    <table className="genie-table">
                      <thead>
                        <tr><th>SKU</th><th>Category</th><th>Stock</th><th>Demand</th><th>Shortfall</th><th>Urgency</th></tr>
                      </thead>
                      <tbody>
                        {trace.stock_advisor.math.skus.filter((s) => s.shortfall > 0).map((r, i) => (
                          <tr key={i}>
                            <td><code>{r.sku_id}</code></td>
                            <td>{r.category}</td>
                            <td>{r.current_stock}</td>
                            <td>{r.projected_monthly_demand}</td>
                            <td>{r.shortfall}</td>
                            <td><span className={`genie-urgency genie-urgency-${r.urgency.toLowerCase()}`}>{r.urgency}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* What-If result */}
            {hasWhatIf && (
              <div className="genie-trace-block">
                <div className="genie-trace-header">
                  <FlaskConical size={14} />
                  <span>What-If Simulation — {trace.what_if.tool}</span>
                </div>
                {trace.what_if.params && Object.keys(trace.what_if.params).length > 0 && (
                  <p className="genie-trace-meta">Params: {JSON.stringify(trace.what_if.params)}</p>
                )}
                {trace.what_if.result?.total_at_risk_skus != null && (
                  <p className="genie-trace-meta">{trace.what_if.result.total_at_risk_skus} SKUs at risk</p>
                )}
                {trace.what_if.result?.products_at_stockout_risk != null && (
                  <p className="genie-trace-meta">{trace.what_if.result.products_at_stockout_risk} products at stockout risk</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  /* ── Confidence badge ───────────────────────────────────────────── */
  const ConfidenceBadge = ({ confidence }) => {
    if (!confidence) return null;
    return (
      <div className="genie-confidence">
        <span className={`confidence-tag confidence-${confidence.level}`}>
          {confidence.tag}
        </span>
      </div>
    );
  };

  /* ── Export button (shown at top of messages with tables) ──────── */
  const ExportButton = ({ trace }) => {
    if (!trace) return null;
    const hasAdvisor = !!trace.stock_advisor;
    if (!hasAdvisor) return null;

    const handleExport = async () => {
      try {
        const response = await exportGenieCsv(trace);
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', `genie_reorder_${new Date().toISOString().slice(0, 10)}.csv`);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
      } catch {
        alert('Export failed. Please try again.');
      }
    };

    return (
      <button className="genie-export-btn genie-export-top" onClick={handleExport} title="Download reorder list as CSV">
        <Download size={12} /> Export CSV
      </button>
    );
  };

  /* ── Render ─────────────────────────────────────────────────────── */
  return (
    <div className="genie-page">
      <Header locationText="Genie — AI-Powered Inventory Intelligence" />

      <div className="genie-layout">
        <div className="genie-chat-container">
          {/* Header */}
          <div className="genie-chat-header">
            <div className="genie-avatar-lg"><Sparkles size={22} /></div>
            <div>
              <h2 className="genie-name">Genie</h2>
              <p className="genie-tagline">VST Inventory Intelligence Assistant</p>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="genie-safety-badge">
                <Shield size={12} />
                SQL agent, forecast integration &amp; what-if simulation
              </div>
              <button className="genie-clear-btn" onClick={clearChat} title="Clear chat">
                <Trash2 size={16} />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="genie-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`genie-message ${msg.role}`}>
                {msg.role === 'assistant' && (
                  <div className="genie-avatar-sm"><Sparkles size={14} /></div>
                )}
                <div className={`genie-bubble ${msg.role}`}>
                  {msg.role === 'assistant' && msg.reasoning_trace && (
                    <div className="genie-bubble-header">
                      <ExportButton trace={msg.reasoning_trace} />
                    </div>
                  )}
                  <div className="genie-bubble-content">
                    {renderMarkdown(msg.content)}
                  </div>
                  {msg.reasoning_trace && <ReasoningTrace trace={msg.reasoning_trace} />}
                  {msg.confidence && msg.role === 'assistant' && (
                    <ConfidenceBadge confidence={msg.confidence} />
                  )}
                </div>
                {msg.role === 'user' && (
                  <div className="genie-user-avatar"><User size={14} /></div>
                )}
              </div>
            ))}

            {isLoading && (
              <div className="genie-message assistant">
                <div className="genie-avatar-sm"><Sparkles size={14} /></div>
                <div className="genie-bubble assistant">
                  <div className="genie-typing"><span /><span /><span /></div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Suggestions */}
          {messages.length <= 2 && suggestions.length > 0 && (
            <div className="genie-suggestions">
              <div className="suggestions-label"><Lightbulb size={14} /> Quick actions</div>
              <div className="suggestions-chips">
                {suggestions.map((s, i) => (
                  <button key={i} className="suggestion-chip" onClick={() => handleSend(s.query)} disabled={isLoading}>
                    {s.text}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Input */}
          <div className="genie-input-area">
            <div className="genie-input-wrapper">
              <textarea
                ref={inputRef}
                className="genie-input"
                placeholder="Ask Genie about inventory, forecasts, what-if scenarios..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                disabled={isLoading}
              />
              <button
                className="genie-send-btn"
                onClick={() => handleSend()}
                disabled={!input.trim() || isLoading}
              >
                {isLoading ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
              </button>
            </div>
            <div className="genie-input-footer">
              Genie uses AI + live data + forecast models. Always verify critical inventory decisions.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
