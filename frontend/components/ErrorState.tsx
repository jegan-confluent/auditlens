export default function ErrorState({ message }: { message: string }) {
  return <div className="panel"><strong>Infrastructure issue</strong><p className="muted">{message}</p></div>;
}
