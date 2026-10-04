export function Device({ children }: { children: React.ReactNode }) {
  return (
    <div className="desk">
      <div className="phone">
        <div className="phone-scroll">{children}</div>
        <span className="phone-mark" aria-hidden="true" />
      </div>
    </div>
  );
}
