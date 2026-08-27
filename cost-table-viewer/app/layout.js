import "./globals.css";

export const metadata = {
  title: "원가표 뷰어",
  description: "구글 시트 기반 원가표를 비밀번호로 보호하여 보여주는 뷰어입니다.",
  manifest: "/manifest.json",
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
  appleWebApp: {
    capable: true,
    title: "원가표 뷰어",
    statusBarStyle: "default",
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#1f6feb",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
