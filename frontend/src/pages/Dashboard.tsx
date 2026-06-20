import React from 'react'
import type { AssistantStatus } from '../hooks/useWebSocket'

interface Props {
  status: AssistantStatus
}

export function Dashboard({ status }: Props) {
  return (
    <div className="dashboard-content">
      <div className="terminal-column">
        <div className="terminal-window">
          <div className="terminal-corner top-left"></div>
          <div className="terminal-corner bottom-right"></div>
          <div className="terminal-prompt"><span className="term-user">devuser@sgcube</span>:~$ neofetch</div>
          <div className="neofetch-output">
            <div className="ascii-art">
              <pre>{`
      .:+oooo+:.
    -/++++++++/-
  -oyyyyyyyyyyyyo-
 ./y:-odNMMMMMNmdo-.:y.
-/yMMMMMMMMMMMMMMMMMxyy--
-hMMMMMMMMMMMMMMMMMMMMMh-
.sMMMMMMMMMMMMMMMMMMMMMMs.
:dMMMMMMMMMMMMMMMMMMMMMMd:
+NMMMMMMMMMMMMMMMMMMMMMMN+
-+MMMMMMMMMMMMMMMMMMMMMM+-
 -hMMMMMMMMMMMMMMMMMMMMh-
  ./y:-odNMMMMMNmdo-.:y.
    -oyyyyyyyyyyyyo-
      -/++++++++/-
        .:+oooo+:.
              `}</pre>
            </div>
            <div className="sys-info">
              <div className="sys-title">devuser@sgcube</div>
              <div className="sys-line"><span className="sys-key">OS:</span> SG Cube OS 2.0 x86_64</div>
              <div className="sys-line"><span className="sys-key">Host:</span> SG-CUBE v2</div>
              <div className="sys-line"><span className="sys-key">Kernel:</span> 6.6.0-sgcube</div>
              <div className="sys-line"><span className="sys-key">Uptime:</span> 2 hours, 47 mins</div>
              <div className="sys-line"><span className="sys-key">Packages:</span> 1542 (sg-pkg)</div>
              <div className="sys-line"><span className="sys-key">Shell:</span> bash 5.2.21</div>
              <div className="sys-line"><span className="sys-key">Resolution:</span> 1920x1080</div>
              <div className="sys-line"><span className="sys-key">DE:</span> SGCube Terminal</div>
              <div className="sys-line"><span className="sys-key">WM:</span> SGWM</div>
              <div className="sys-line"><span className="sys-key">Theme:</span> SG-Dark [GTK3]</div>
              <div className="sys-line"><span className="sys-key">Icons:</span> SGCube-Icons [GTK3]</div>
              <div className="sys-line"><span className="sys-key">Terminal:</span> sgcube-terminal</div>
              <div className="sys-line"><span className="sys-key">CPU:</span> Intel i7-12700K (20) @ 5.00GHz</div>
              <div className="sys-line"><span className="sys-key">GPU:</span> NVIDIA GeForce RTX 3080</div>
              <div className="sys-line"><span className="sys-key">Memory:</span> 4.23GiB / 31.32GiB</div>
              <div className="color-blocks">
                <span className="cb cb-black"></span>
                <span className="cb cb-red"></span>
                <span className="cb cb-green"></span>
                <span className="cb cb-yellow"></span>
                <span className="cb cb-blue"></span>
                <span className="cb cb-magenta"></span>
                <span className="cb cb-cyan"></span>
                <span className="cb cb-white"></span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="terminal-window status-term">
          <div className="terminal-corner top-left"></div>
          <div className="terminal-corner bottom-right"></div>
          <div className="terminal-prompt"><span className="term-user">devuser@sgcube</span>:~$ sgcube status</div>
          <div className="sgcube-status-box">
            <div className="status-box-header">
               <svg width="140" height="20" viewBox="0 0 140 20">
                  <path d="M0,20 L0,5 L5,0 L135,0 L140,5 L140,20" fill="none" stroke="var(--border-bright)" strokeWidth="1" />
                  <text x="70" y="14" fill="var(--border-bright)" fontSize="11" fontFamily="var(--font-mono)" textAnchor="middle" letterSpacing="1">SG CUBE STATUS</text>
               </svg>
            </div>
            <div className="status-box-content">
               <div className="status-col">
                 <div className="sys-line"><span className="sys-key">ENVIRONMENT</span> PRODUCTION</div>
                 <div className="sys-line"><span className="sys-key">VERSION</span> v2.0.0</div>
                 <div className="sys-line"><span className="sys-key">UPTIME</span> 2h 47m 13s</div>
                 <div className="sys-line"><span className="sys-key">LAST DEPLOY</span> 2024-05-23 14:35:10</div>
               </div>
               <div className="status-col right-aligned">
                 <div className="sys-line"><span className="db-icon">⛁</span> Database <span className="status-ok">[ OK ]</span></div>
                 <div className="sys-line"><span className="db-icon">⚡</span> API Gateway <span className="status-ok">[ OK ]</span></div>
                 <div className="sys-line"><span className="db-icon">🛡</span> Auth Service <span className="status-ok">[ OK ]</span></div>
                 <div className="sys-line"><span className="db-icon">📁</span> Storage <span className="status-ok">[ OK ]</span></div>
                 <div className="sys-line"><span className="db-icon">⛭</span> Cache <span className="status-ok">[ OK ]</span></div>
               </div>
            </div>
          </div>
          <div className="terminal-prompt mt-4"><span className="term-user">devuser@sgcube</span>:~$ <span className="cursor">█</span></div>
        </div>
      </div>

      <div className="center-cube-illustration">
         <div className="hud-rings">
            <svg viewBox="0 0 500 500" width="500" height="500">
               {/* Outer target ring */}
               <circle cx="250" cy="250" r="230" fill="none" stroke="var(--text-dim)" strokeWidth="1" opacity="0.3" strokeDasharray="1 10" className="spin-slow" />
               <circle cx="250" cy="250" r="220" fill="none" stroke="var(--border-bright)" strokeWidth="1" opacity="0.2" strokeDasharray="5 15" />
               {/* Complex tick marks ring */}
               <circle cx="250" cy="250" r="200" fill="none" stroke="var(--border-bright)" strokeWidth="4" opacity="0.4" strokeDasharray="2 6" className="spin-slow-reverse" />
               <circle cx="250" cy="250" r="200" fill="none" stroke="var(--border-bright)" strokeWidth="1" opacity="0.3" />
               
               {/* Thicker inner boundary */}
               <circle cx="250" cy="250" r="180" fill="none" stroke="var(--border-bright)" strokeWidth="2" opacity="0.1" />
               <circle cx="250" cy="250" r="175" fill="none" stroke="var(--text-bright)" strokeWidth="1" opacity="0.3" strokeDasharray="20 40" className="spin-slow" />
               
               {/* Central data ring */}
               <circle cx="250" cy="250" r="150" fill="none" stroke="var(--border-bright)" strokeWidth="3" opacity="0.8" strokeDasharray="80 20 10 20 40 20" className="spin-slow" />
               <circle cx="250" cy="250" r="145" fill="none" stroke="var(--border-bright)" strokeWidth="1" opacity="0.5" />
               
               {/* Inner dashed ring */}
               <circle cx="250" cy="250" r="120" fill="none" stroke="var(--text-primary)" strokeWidth="1" opacity="0.6" strokeDasharray="10 5" className="spin-slow-reverse" />
               
               {/* Crosshairs & Reticle marks */}
               <line x1="250" y1="0" x2="250" y2="30" stroke="var(--border-bright)" strokeWidth="2" opacity="0.8"/>
               <line x1="250" y1="470" x2="250" y2="500" stroke="var(--border-bright)" strokeWidth="2" opacity="0.8"/>
               <line x1="0" y1="250" x2="30" y2="250" stroke="var(--border-bright)" strokeWidth="2" opacity="0.8"/>
               <line x1="470" y1="250" x2="500" y2="250" stroke="var(--border-bright)" strokeWidth="2" opacity="0.8"/>
               
               {/* Target brackets */}
               <path d="M 100 100 L 120 100 M 100 100 L 100 120" fill="none" stroke="var(--border-bright)" strokeWidth="2" opacity="0.6" />
               <path d="M 400 100 L 380 100 M 400 100 L 400 120" fill="none" stroke="var(--border-bright)" strokeWidth="2" opacity="0.6" />
               <path d="M 100 400 L 120 400 M 100 400 L 100 380" fill="none" stroke="var(--border-bright)" strokeWidth="2" opacity="0.6" />
               <path d="M 400 400 L 380 400 M 400 400 L 400 380" fill="none" stroke="var(--border-bright)" strokeWidth="2" opacity="0.6" />
            </svg>
         </div>
         <div className="cube-container">
            <div className="cube">
               <div className="face front">SG</div>
               <div className="face back"></div>
               <div className="face right">CUBE</div>
               <div className="face left"></div>
               <div className="face top"></div>
               <div className="face bottom"></div>
            </div>
         </div>
      </div>
    </div>
  )
}
