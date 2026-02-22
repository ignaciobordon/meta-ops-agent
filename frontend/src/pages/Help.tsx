import { useState } from 'react';
import { HelpCircle, Book, Zap, Settings, AlertCircle, CheckCircle } from 'lucide-react';
import './Help.css';

interface FAQItem {
  question: string;
  answer: string;
  category: string;
}

export default function Help() {
  const [activeTab, setActiveTab] = useState<'tutorial' | 'faq' | 'api'>('tutorial');
  const [expandedFAQ, setExpandedFAQ] = useState<number | null>(null);

  const faqs: FAQItem[] = [
    {
      category: 'Getting Started',
      question: 'What is Renaissance?',
      answer: 'Renaissance is an AI-powered system that helps you manage Meta (Facebook/Instagram) advertising campaigns. It analyzes your ad performance, suggests optimizations, and can automatically execute approved changes while following strict safety rules.',
    },
    {
      category: 'Getting Started',
      question: 'How do I connect my Meta Ads account?',
      answer: 'Go to Control Panel → Click "Connect Meta Account" → Login with your Facebook credentials → Select which ad accounts to manage. You need ads_management permissions.',
    },
    {
      category: 'Getting Started',
      question: 'Is it safe to use? Will it change my campaigns without permission?',
      answer: 'YES, it\'s safe! By default, "Operator Armed" is OFF, meaning NO changes can be made to your real campaigns. All actions run in DRY_RUN mode (simulation only). You must explicitly enable Operator Armed AND approve each decision before any real changes happen.',
    },
    {
      category: 'Decision Workflow',
      question: 'What is the decision approval workflow?',
      answer: 'Every change follows this flow: 1) Draft created → 2) Policy validation → 3) Request approval → 4) Director approves → 5) Execute (dry-run or live). You have control at every step.',
    },
    {
      category: 'Decision Workflow',
      question: 'What does "Operator Armed" mean?',
      answer: 'Operator Armed is a safety switch. When OFF (default), all executions are simulated (dry-run). When ON, approved decisions can make REAL changes to your Meta campaigns. Only Admins can toggle this.',
    },
    {
      category: 'Decision Workflow',
      question: 'Can I rollback a change if something goes wrong?',
      answer: 'Yes! The Operator has a rollback_last() function that reverses the most recent action. This bypasses policy checks since it\'s a corrective action.',
    },
    {
      category: 'Creatives',
      question: 'How do I generate new ad creatives?',
      answer: 'Go to Creatives page → Click "Generate New" → Select angle (transformation, community, etc) → System uses AI to write ad scripts based on your brand voice. Scripts are scored automatically.',
    },
    {
      category: 'Creatives',
      question: 'What is a "creative score"?',
      answer: 'A 0-100% score measuring how well the ad script aligns with your brand identity and target audience. Scores below 70% are flagged for review.',
    },
    {
      category: 'Saturation',
      question: 'What does "saturated" mean for an angle?',
      answer: 'Saturation measures audience fatigue. "Fresh" (0-40%) = high potential, scale up. "Moderate" (40-70%) = monitor closely. "Saturated" (70%+) = rotate out, audience is tired of this messaging.',
    },
    {
      category: 'Saturation',
      question: 'How is saturation calculated?',
      answer: 'Weighted composite: Frequency (35%) + CTR decay (35%) + CPM inflation (30%). If people see your ads too often and stop clicking, saturation increases.',
    },
    {
      category: 'Policies',
      question: 'What are policy rules?',
      answer: 'Safety guardrails that prevent dangerous changes. Examples: Budget changes limited to ±20%, 24-hour cooldown between edits, no changes during learning phase. These protect your account from instability.',
    },
    {
      category: 'Policies',
      question: 'Can I customize policy rules?',
      answer: 'Currently, rules are hard-coded with sensible defaults. Future versions will allow per-organization customization (e.g., change budget delta from ±20% to ±30%).',
    },
    {
      category: 'Opportunities',
      question: 'Where do opportunities come from?',
      answer: 'From your BrandMap competitive analysis. The system identifies gaps where competitors are weak (e.g., "they ignore community, you should own that angle").',
    },
    {
      category: 'Opportunities',
      question: 'How do I act on an opportunity?',
      answer: 'Click "Create Campaign" on an opportunity → It will draft a new campaign decision pre-filled with the recommended strategy → Submit for approval.',
    },
    {
      category: 'Technical',
      question: 'What happens in "Dry Run" mode?',
      answer: 'System simulates the API call to Meta but doesn\'t actually execute. You see what WOULD happen without risk. All decisions default to dry-run for safety.',
    },
    {
      category: 'Technical',
      question: 'Why did my decision get blocked by policy?',
      answer: 'Check the Policies page to see which rule failed. Common reasons: budget change too large, campaign in learning phase, or tried to edit same entity within 24 hours.',
    },
    {
      category: 'Technical',
      question: 'How do I see what the system has done?',
      answer: 'Go to Audit Log page. Every execution (successful, failed, or dry-run) is logged with timestamp, user, changes, and trace ID for debugging.',
    },
    {
      category: 'Troubleshooting',
      question: 'Pages are blank or not loading data',
      answer: 'Check if backend is running at localhost:8000. Try: curl http://localhost:8000/api/health. If it fails, restart backend with: python run_server.py',
    },
    {
      category: 'Troubleshooting',
      question: 'Frontend shows "Failed to fetch" errors',
      answer: 'Backend is not running or CORS issue. Verify backend is up, check browser console for errors, ensure localhost:8000 is accessible.',
    },
    {
      category: 'Troubleshooting',
      question: 'Meta API returns "Invalid token" error',
      answer: 'Your access token expired (they last 60 days). Re-authenticate: Control Panel → Reconnect Meta Account.',
    },
  ];

  const tutorialSections = [
    {
      title: '1. Getting Started',
      icon: Zap,
      steps: [
        'Open Renaissance at http://localhost:5173',
        'Click on "Control Panel" in the sidebar',
        'Click "Connect Meta Account" and login with Facebook',
        'Select which ad accounts you want to manage',
        'Grant "ads_management" and "ads_read" permissions',
      ],
    },
    {
      title: '2. Understanding the Dashboard',
      icon: Book,
      steps: [
        'Dashboard shows overview: total spend, active campaigns, pending decisions',
        'Quick stats on saturation levels and policy violations',
        'Recent activity feed shows latest system actions',
        'Navigate using sidebar: Dashboard, Decisions, Control Panel, etc.',
      ],
    },
    {
      title: '3. Creating a Decision',
      icon: Settings,
      steps: [
        'Go to "Control Panel" page',
        'Select "Budget Change" or other action type',
        'Choose which campaign/adset to modify',
        'Enter new values (e.g., increase budget from $100 to $120)',
        'Add rationale explaining why (required for audit)',
        'Click "Create Draft" - decision enters DRAFT state',
      ],
    },
    {
      title: '4. Approving & Executing',
      icon: CheckCircle,
      steps: [
        'Go to "Decision Queue" page',
        'Click "Validate" on your draft → Policy Engine checks rules',
        'If READY (green), click "Request Approval"',
        'As Director/Admin, click "Approve"',
        'Click "Execute" → Choose Dry Run (safe) or Live (requires Operator Armed ON)',
        'Check "Audit Log" to see execution result',
      ],
    },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <HelpCircle size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Help & Documentation</h1>
            <p className="page-description">
              Learn how to use Renaissance effectively
            </p>
          </div>
        </div>
      </div>

      <div className="help-tabs">
        <button
          className={`help-tab ${activeTab === 'tutorial' ? 'active' : ''}`}
          onClick={() => setActiveTab('tutorial')}
        >
          <Book size={18} />
          Tutorial
        </button>
        <button
          className={`help-tab ${activeTab === 'faq' ? 'active' : ''}`}
          onClick={() => setActiveTab('faq')}
        >
          <HelpCircle size={18} />
          FAQ
        </button>
        <button
          className={`help-tab ${activeTab === 'api' ? 'active' : ''}`}
          onClick={() => setActiveTab('api')}
        >
          <Settings size={18} />
          API Connection
        </button>
      </div>

      {activeTab === 'tutorial' && (
        <div className="tutorial-content">
          <div className="tutorial-intro">
            <AlertCircle size={24} className="intro-icon" />
            <div>
              <h3>Quick Start Guide</h3>
              <p>
                Follow these steps to set up and start using Renaissance.
                Everything is safe by default - no changes will be made until you explicitly approve them.
              </p>
            </div>
          </div>

          {tutorialSections.map((section, idx) => {
            const Icon = section.icon;
            return (
              <div key={idx} className="tutorial-section">
                <div className="tutorial-header">
                  <Icon size={24} />
                  <h3>{section.title}</h3>
                </div>
                <ol className="tutorial-steps">
                  {section.steps.map((step, stepIdx) => (
                    <li key={stepIdx}>{step}</li>
                  ))}
                </ol>
              </div>
            );
          })}

          <div className="tutorial-warning">
            <AlertCircle size={20} />
            <div>
              <strong>Safety First!</strong>
              <p>
                By default, "Operator Armed" is OFF. This means all executions are simulated (dry-run).
                No real changes will be made to your Meta campaigns until you:
                1) Toggle Operator Armed ON (Admin only), and
                2) Explicitly choose "Execute Live" on an approved decision.
              </p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'faq' && (
        <div className="faq-content">
          <div className="faq-categories">
            {['Getting Started', 'Decision Workflow', 'Creatives', 'Saturation', 'Policies', 'Opportunities', 'Technical', 'Troubleshooting'].map((category) => (
              <div key={category} className="faq-category">
                <h3 className="faq-category-title">{category}</h3>
                {faqs
                  .filter((faq) => faq.category === category)
                  .map((faq, idx) => {
                    const globalIdx = faqs.indexOf(faq);
                    const isExpanded = expandedFAQ === globalIdx;
                    return (
                      <div key={idx} className="faq-item">
                        <button
                          className="faq-question"
                          onClick={() => setExpandedFAQ(isExpanded ? null : globalIdx)}
                        >
                          <HelpCircle size={16} />
                          <span>{faq.question}</span>
                          <span className="faq-toggle">{isExpanded ? '−' : '+'}</span>
                        </button>
                        {isExpanded && (
                          <div className="faq-answer">
                            <p>{faq.answer}</p>
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'api' && (
        <div className="api-content">
          <div className="api-section">
            <h3>Connecting Your Meta Ads Account</h3>
            <p>Follow these steps to connect Renaissance to your Facebook/Instagram advertising accounts.</p>

            <div className="api-step">
              <div className="step-number">1</div>
              <div className="step-content">
                <h4>Create a Meta App (First Time Only)</h4>
                <ol>
                  <li>Go to <a href="https://developers.facebook.com/apps" target="_blank" rel="noopener noreferrer">Meta for Developers</a></li>
                  <li>Click "Create App" → Select "Business" type</li>
                  <li>Fill in App Name: "Renaissance"</li>
                  <li>Copy your <strong>App ID</strong> and <strong>App Secret</strong></li>
                  <li>Add to your <code>.env</code> file:</li>
                </ol>
                <pre className="code-block">
META_APP_ID=your_app_id_here{'\n'}
META_APP_SECRET=your_app_secret_here
                </pre>
              </div>
            </div>

            <div className="api-step">
              <div className="step-number">2</div>
              <div className="step-content">
                <h4>Enable Marketing API</h4>
                <ol>
                  <li>In your Meta App → Add Product → Select "Marketing API"</li>
                  <li>Request Standard Access for these permissions:</li>
                  <ul>
                    <li><code>ads_management</code> - Create/edit/delete campaigns</li>
                    <li><code>ads_read</code> - Read campaign data and insights</li>
                    <li><code>business_management</code> - Manage Business Manager assets</li>
                  </ul>
                  <li>Note: Standard Access requires Meta's App Review (takes 3-5 days)</li>
                </ol>
              </div>
            </div>

            <div className="api-step">
              <div className="step-number">3</div>
              <div className="step-content">
                <h4>Connect in Control Panel</h4>
                <ol>
                  <li>Go to <strong>Control Panel</strong> page</li>
                  <li>Click <strong>"Connect Meta Account"</strong> button</li>
                  <li>Login with your Facebook credentials</li>
                  <li>Authorize the requested permissions</li>
                  <li>Select which ad accounts to manage</li>
                </ol>
                <p>✅ You're connected! The system can now read your campaigns and suggest optimizations.</p>
              </div>
            </div>

            <div className="api-step">
              <div className="step-number">4</div>
              <div className="step-content">
                <h4>Managing Multiple Accounts</h4>
                <p>Renaissance supports multi-tenant architecture:</p>
                <ul>
                  <li><strong>Organization</strong> = Your workspace (e.g., "Acme Marketing Agency")</li>
                  <li><strong>Meta Connection</strong> = One Business Manager connection per org</li>
                  <li><strong>Ad Accounts</strong> = Multiple client accounts under one connection</li>
                </ul>
                <p>Each ad account can have different settings and users with specific roles (Viewer, Operator, Director, Admin).</p>
              </div>
            </div>
          </div>

          <div className="api-warning">
            <AlertCircle size={20} />
            <div>
              <strong>Important: Token Expiration</strong>
              <p>
                Meta access tokens expire after 60 days. You'll need to re-authenticate periodically.
                The system will notify you when tokens are about to expire.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
