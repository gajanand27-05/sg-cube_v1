import { Camera, Car, User, Bike, Type } from 'lucide-react'

export function VisionModuleWidget() {
  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Camera size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          VISION MODULE
        </div>
        <div className="text-[#00ff41] text-[10px] font-mono tracking-widest uppercase">
          LIVE
        </div>
      </div>

      <div className="flex gap-4 mb-4">
        {/* Radar sweep hero */}
        <div className="w-[120px] h-[80px] bg-[#050a14] border border-sgc-border rounded overflow-hidden relative shrink-0">
          <svg viewBox="0 0 120 80" className="w-full h-full" style={{ filter: 'drop-shadow(0 0 5px rgba(249,115,22,0.55))' }}>
            <circle cx="60" cy="40" r="34" fill="none" stroke="#f97316" strokeWidth="1.5" strokeOpacity="0.3" />
            <circle cx="60" cy="40" r="22" fill="none" stroke="#f97316" strokeWidth="1.5" strokeOpacity="0.3" />
            <circle cx="60" cy="40" r="10" fill="none" stroke="#f97316" strokeWidth="1.5" strokeOpacity="0.3" />
            <line x1="60" y1="6" x2="60" y2="74" stroke="#f97316" strokeWidth="1.5" strokeOpacity="0.2" />
            <line x1="26" y1="40" x2="94" y2="40" stroke="#f97316" strokeWidth="1.5" strokeOpacity="0.2" />
            <path d="M60 40 L94 40 A34 34 0 0 1 76 14 Z" fill="#f97316" opacity="0.18"
              style={{ transformOrigin: '60px 40px', animation: 'radar-sweep 4s linear infinite' }} />
            <circle cx="74" cy="28" r="2" fill="#00ff41" className="animate-pulse" />
          </svg>
          <div className="absolute top-1 right-1 flex items-center gap-1">
             <div className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" />
             <span className="text-[8px] font-mono text-red-500 tracking-widest">REC</span>
          </div>
        </div>
        
        {/* Detected List */}
        <div className="flex-1 flex flex-col gap-1.5 tp-3 justify-center">
          <div className="text-sgc-bright mb-1 border-b border-sgc-border pb-1">Detected</div>
          
          <div className="flex items-center gap-2 text-sgc-bright">
            <User size={12} className="text-[#00aaff]" />
            <span>Person (98%)</span>
          </div>
          <div className="flex items-center gap-2 text-sgc-bright">
            <Car size={12} className="text-sgc-dim" />
            <span>Car (85%)</span>
          </div>
          <div className="flex items-center gap-2 text-sgc-bright">
            <Bike size={12} className="text-sgc-dim" />
            <span>Bicycle (42%)</span>
          </div>
        </div>
      </div>

      <div className="tp-3 border-t border-sgc-border pt-2 flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-sgc-bright">
          <Type size={12} className="text-sgc-primary" />
          <span>OCR: <span className="text-sgc-primary ml-1">STOP</span></span>
        </div>
        <div className="flex justify-between items-center">
          <span>Camera</span>
          <span className="text-sgc-bright">Cam_01 (1080p)</span>
        </div>
      </div>
    </div>
  )
}
