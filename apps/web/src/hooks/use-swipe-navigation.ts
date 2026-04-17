import { useCallback, useEffect, useRef } from "react";
import { useMotionValue } from "motion/react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

export function useSwipeNavigation() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const location = useLocation();

  const scrollRef = useRef<HTMLDivElement>(null);
  const programmaticScroll = useRef(false);
  const scrollEndTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const base = `/agent/${encodeURIComponent(name!)}`;
  const isDashboard = location.pathname === base;
  const isChat = location.pathname === `${base}/chat`;
  const isSubpage = !isDashboard && !isChat;
  const progress = useMotionValue(isChat ? 1 : 0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || isSubpage) return;
    const target = isChat ? el.clientWidth : 0;
    progress.set(isChat ? 1 : 0);
    if (Math.abs(el.scrollLeft - target) > 1) {
      programmaticScroll.current = true;
      el.scrollTo({ left: target, behavior: "smooth" });
    }
  }, [progress, isChat, isSubpage]);

  const handleScrollEnd = useCallback(() => {
    if (programmaticScroll.current) {
      programmaticScroll.current = false;
      return;
    }
    const el = scrollRef.current;
    if (!el) return;
    const page = Math.round(el.scrollLeft / el.clientWidth);
    if (page === 0 && !isDashboard) navigate(base, { replace: true });
    else if (page === 1 && !isChat) navigate(`${base}/chat`, { replace: true });
  }, [isDashboard, isChat, navigate, base]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el || el.clientWidth <= 0) return;

    if (!programmaticScroll.current) {
      progress.set(el.scrollLeft / el.clientWidth);
    }

    if (scrollEndTimeout.current) {
      clearTimeout(scrollEndTimeout.current);
    }

    scrollEndTimeout.current = setTimeout(handleScrollEnd, 100);
  }, [progress, handleScrollEnd]);

  useEffect(() => {
    return () => {
      if (scrollEndTimeout.current) {
        clearTimeout(scrollEndTimeout.current);
      }
    };
  }, []);

  return { scrollRef, handleScroll, progress, isSubpage };
}
