/* ============================================================
   Клуб «Царство» — Interactions
   ============================================================ */

(function () {
  "use strict";

  // Telegram bot — replace with your real bot username/link
  const TELEGRAM_BOT = "https://t.me/tsarstvo_club_bot";
  const TELEGRAM_SUPPORT = "https://t.me/tsarstvo_club_bot";

  // Payment links per product (placeholder payment URLs → open via bot with product context)
  const PAYMENT_LINKS = {
    micro: TELEGRAM_BOT + "?start=pay_micro_555",
    mini: TELEGRAM_BOT + "?start=pay_mini_1554",
    group: TELEGRAM_BOT + "?start=pay_group_12000",
    curator: TELEGRAM_BOT + "?start=pay_curator_18000",
    mentor: TELEGRAM_BOT + "?start=pay_mentor_55000",
    annual: TELEGRAM_BOT + "?start=pay_annual_555000",
  };

  // Expose for inline use
  window.TSARSTVO = { TELEGRAM_BOT, TELEGRAM_SUPPORT, PAYMENT_LINKS };

  /* ---------- Navbar scroll ---------- */
  const navbar = document.querySelector(".navbar");
  const onScroll = () => {
    if (!navbar) return;
    navbar.classList.toggle("scrolled", window.scrollY > 24);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Mobile menu ---------- */
  const toggle = document.querySelector(".nav-toggle");
  const navLinks = document.querySelector(".nav-links");
  if (toggle && navLinks) {
    toggle.addEventListener("click", () => {
      const open = toggle.classList.toggle("open");
      navLinks.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      document.body.style.overflow = open ? "hidden" : "";
    });
    navLinks.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => {
        toggle.classList.remove("open");
        navLinks.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        document.body.style.overflow = "";
      });
    });
  }

  /* ---------- Scroll reveal ---------- */
  const revealEls = document.querySelectorAll(".reveal, .stagger-children");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealEls.forEach((el) => io.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add("visible"));
  }

  /* ---------- FAQ accordion ---------- */
  document.querySelectorAll(".faq-item").forEach((item) => {
    const btn = item.querySelector(".faq-question");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const isOpen = item.classList.contains("open");
      document.querySelectorAll(".faq-item.open").forEach((other) => {
        if (other !== item) {
          other.classList.remove("open");
          other.querySelector(".faq-question")?.setAttribute("aria-expanded", "false");
        }
      });
      item.classList.toggle("open", !isOpen);
      btn.setAttribute("aria-expanded", !isOpen ? "true" : "false");
    });
  });

  /* ---------- Payment buttons ---------- */
  document.querySelectorAll("[data-pay]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const key = btn.getAttribute("data-pay");
      const url = PAYMENT_LINKS[key] || TELEGRAM_BOT;
      window.open(url, "_blank", "noopener,noreferrer");
    });
  });

  /* ---------- Lead form → Telegram bot ---------- */
  const form = document.getElementById("lead-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = (form.querySelector('[name="name"]')?.value || "").trim();
      const phone = (form.querySelector('[name="phone"]')?.value || "").trim();
      const interest = form.querySelector('[name="interest"]')?.value || "";
      const message = (form.querySelector('[name="message"]')?.value || "").trim();

      if (!name || !phone) {
        shakeForm(form);
        return;
      }

      // Build deep-link payload for bot
      const payload = [
        "lead",
        slugify(name).slice(0, 20),
        slugify(interest).slice(0, 20) || "general",
      ]
        .filter(Boolean)
        .join("_");

      const text = encodeURIComponent(
        [
          "Здравствуйте! Хочу в Клуб «Царство».",
          "",
          `Имя: ${name}`,
          `Телефон: ${phone}`,
          interest ? `Интерес: ${interest}` : "",
          message ? `Сообщение: ${message}` : "",
        ]
          .filter(Boolean)
          .join("\n")
      );

      // Prefer start param; also pass text via share URL fallback
      const botUrl = `${TELEGRAM_BOT}?start=${encodeURIComponent(payload)}`;
      // Open bot; user can paste prefilled text if bot supports it
      window.open(botUrl, "_blank", "noopener,noreferrer");

      // Also try tg:// with text for better UX on mobile
      setTimeout(() => {
        // Show success state
        const card = form.closest(".form-card");
        const success = card?.querySelector(".form-success");
        if (success) {
          form.style.display = "none";
          success.classList.add("show");
        }
      }, 400);

      // Store for optional re-open with message
      try {
        sessionStorage.setItem(
          "tsarstvo_lead",
          JSON.stringify({ name, phone, interest, message, text })
        );
      } catch (_) {}
    });
  }

  function slugify(s) {
    return s
      .toLowerCase()
      .replace(/[а-яё]/gi, (ch) => {
        const map = {
          а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e",
          ж: "zh", з: "z", и: "i", й: "y", к: "k", л: "l", м: "m",
          н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u",
          ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sch",
          ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
        };
        return map[ch.toLowerCase()] || ch;
      })
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "");
  }

  function shakeForm(el) {
    el.style.animation = "none";
    void el.offsetWidth;
    el.style.animation = "form-shake 0.45s ease";
  }

  // Inject shake keyframes
  const style = document.createElement("style");
  style.textContent = `
    @keyframes form-shake {
      0%, 100% { transform: translateX(0); }
      20% { transform: translateX(-8px); }
      40% { transform: translateX(8px); }
      60% { transform: translateX(-5px); }
      80% { transform: translateX(5px); }
    }
  `;
  document.head.appendChild(style);

  /* ---------- Smooth anchor offset for fixed nav ---------- */
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      if (!id || id === "#") return;
      const target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top, behavior: "smooth" });
    });
  });

  /* ---------- Active nav link ---------- */
  const path = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".nav-links a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    if (href === path || (path === "" && href === "index.html")) {
      a.classList.add("active");
    }
  });

  /* ---------- Parallax-lite on hero portrait ---------- */
  const portrait = document.querySelector(".hero-portrait");
  if (portrait && window.matchMedia("(pointer: fine)").matches) {
    const visual = portrait.closest(".hero-visual");
    visual?.addEventListener("mousemove", (e) => {
      const rect = visual.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      portrait.style.transform = `scale(1.05) translate(${x * 8}px, ${y * 8}px)`;
    });
    visual?.addEventListener("mouseleave", () => {
      portrait.style.transform = "";
    });
  }
})();
