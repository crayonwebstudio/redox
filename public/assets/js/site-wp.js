// Front-end behaviour for the converted site. No backend is involved:
// the contact form opens the visitor's email app addressed to Woodwolf
// Digital, and subscribe forms show an honest pending state.
document.addEventListener('DOMContentLoaded', () => {
  // Background images set through data-background attributes.
  document.querySelectorAll('[data-background]').forEach((el) => {
    const url = el.getAttribute('data-background');
    if (url) el.style.backgroundImage = 'url(' + url + ')';
  });

  // Sliders: initialise Swiper on every slider container present.
  if (window.Swiper) {
    document.querySelectorAll('.swiper, .swiper-container').forEach((el) => {
      if (el.classList.contains('swiper-initialized')) return;
      try {
        new window.Swiper(el, {
          slidesPerView: 'auto',
          spaceBetween: 20,
          loop: false,
          autoplay: false,
        });
      } catch (e) { /* leave slides as a plain row if init fails */ }
    });
  }

  // Counters: the original widget animates from its starting value to
  // the target when scrolled into view, and that animation script is not
  // shipped. The markup already carries the final value (rendered by the
  // generator), so the correct number shows even without JavaScript; with
  // it, the count-up runs once on first view, using the widget's own
  // duration, starting value, target, and delimiter attributes.
  const formatCounter = (value, delimiter, decimals) => {
    const fixed = decimals > 0 ? value.toFixed(decimals) : String(Math.round(value));
    const parts = fixed.split('.');
    let intPart = parts[0];
    if (delimiter) {
      let grouped = '';
      while (intPart.length > 3) {
        grouped = delimiter + intPart.slice(-3) + grouped;
        intPart = intPart.slice(0, -3);
      }
      intPart = intPart + grouped;
    }
    return decimals > 0 ? intPart + '.' + (parts[1] || '') : intPart;
  };
  document.querySelectorAll('.elementor-counter-number').forEach((el) => {
    const to = parseFloat(el.getAttribute('data-to-value'));
    if (Number.isNaN(to)) return;
    const from = parseFloat(el.getAttribute('data-from-value') || '0') || 0;
    const duration = parseInt(el.getAttribute('data-duration') || '2000', 10) || 2000;
    const delimiter = el.getAttribute('data-delimiter') || '';
    const rawTo = el.getAttribute('data-to-value') || '';
    const decimals = rawTo.indexOf('.') >= 0 ? rawTo.split('.')[1].length : 0;
    const finalText = formatCounter(to, delimiter, decimals);
    if (!('IntersectionObserver' in window)) return; // markup already final
    el.textContent = formatCounter(from, delimiter, decimals);
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        if (duration <= 0) { el.textContent = finalText; return; }
        const start = performance.now();
        const step = (now) => {
          const t = Math.min((now - start) / duration, 1);
          const eased = 1 - Math.pow(1 - t, 3);
          el.textContent = formatCounter(from + (to - from) * eased, delimiter, decimals);
          if (t < 1) requestAnimationFrame(step);
          else el.textContent = finalText;
        };
        requestAnimationFrame(step);
      });
    }, { threshold: 0.25 });
    observer.observe(el);
  });

  // Off-canvas panel.
  const panel = document.querySelector('.offcanvas-area');
  const overlay = document.createElement('div');
  overlay.className = 'offcanvas-overlay';
  document.body.appendChild(overlay);
  const open = () => { if (panel) panel.classList.add('open'); overlay.classList.add('open'); };
  const close = () => { if (panel) panel.classList.remove('open'); overlay.classList.remove('open'); };
  document.querySelectorAll('.side-toggle').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); open(); }));
  document.querySelectorAll('.offcanvas-close, .side-info-close').forEach((b) => b.addEventListener('click', close));
  overlay.addEventListener('click', close);

  // Back to top.
  const topBtn = document.getElementById('back-to-top');
  if (topBtn) {
    window.addEventListener('scroll', () => {
      topBtn.classList.toggle('visible', window.scrollY > 400);
    });
    topBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  }

  const statusFor = (form) => {
    let el = form.parentElement ? form.parentElement.querySelector('.form-status') : null;
    if (!el) {
      el = document.createElement('p');
      el.className = 'form-status';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      form.insertAdjacentElement('afterend', el);
    }
    return el;
  };

  const contactForm = document.getElementById('contact__form');
  if (contactForm) {
    contactForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const status = statusFor(contactForm);
      const get = (name) => {
        const f = contactForm.querySelector('[name="' + name + '"]');
        return f ? f.value.trim() : '';
      };
      const name = get('name');
      const email = get('email');
      if (!name || !email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        status.dataset.state = 'error';
        status.textContent = 'Please enter your name and a valid email address before sending.';
        return;
      }
      const subject = encodeURIComponent('Website enquiry from ' + name);
      const body = encodeURIComponent(
        ['Name: ' + name, 'Email: ' + email,
         get('phone') ? 'Phone: ' + get('phone') : '',
         get('company') ? 'Company: ' + get('company') : '',
         get('budget') ? 'Budget: ' + get('budget') : '',
         get('solution') ? 'Solution: ' + get('solution') : '', '',
         get('message')].filter(Boolean).join('\n')
      );
      status.dataset.state = '';
      status.textContent = 'Opening your email app with this message addressed to info@woodwolfdigital.com.';
      window.location.href = 'mailto:info@woodwolfdigital.com?subject=' + subject + '&body=' + body;
    });
  }

  document.querySelectorAll('form.subscribe-form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const status = statusFor(form);
      const input = form.querySelector('input[type="email"]');
      const email = input ? input.value.trim() : '';
      if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        status.dataset.state = 'error';
        status.textContent = 'Please enter a valid email address to subscribe.';
        return;
      }
      status.dataset.state = '';
      status.textContent = 'Thank you. Your subscription request was noted on this page; a mailing backend is not connected yet, so please email info@woodwolfdigital.com if you need confirmation.';
    });
  });
});
