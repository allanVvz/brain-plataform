import "./globals.css";
import AppShell from "./AppShell";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('ai-brain-theme');document.documentElement.setAttribute('data-theme',t==='dark'?'dark':'clean');}catch(e){document.documentElement.setAttribute('data-theme','clean');}})();`,
          }}
        />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
