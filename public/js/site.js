// Front-end form handling. There is no PHP mail backend in the Astro build:
// the contact form opens the visitor's email app addressed to Woodwolf Digital,
// and subscribe forms show an honest pending state until a backend is connected.
document.addEventListener('DOMContentLoaded', () => {
  const statusFor = (form) => {
    let el = form.parentElement?.querySelector('.form-status');
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
      const get = (name) => contactForm.querySelector(`[name="${name}"]`)?.value?.trim() || '';
      const name = get('name');
      const email = get('email');
      const phone = get('phone');
      const company = get('company');
      const solution = get('solution');
      const message = get('message') || contactForm.querySelector('textarea')?.value?.trim() || '';
      if (!name || !email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        status.dataset.state = 'error';
        status.textContent = 'Please enter your name and a valid email address before sending.';
        return;
      }
      const subject = encodeURIComponent(`Website enquiry from ${name}`);
      const body = encodeURIComponent(
        [`Name: ${name}`, `Email: ${email}`, phone ? `Phone: ${phone}` : '', company ? `Company: ${company}` : '', solution ? `Solution: ${solution}` : '', '', message].filter(Boolean).join('\n')
      );
      status.dataset.state = '';
      status.textContent = 'Opening your email app with this message addressed to info@woodwolfdigital.com.';
      window.location.href = `mailto:info@woodwolfdigital.com?subject=${subject}&body=${body}`;
    });
  }

  document.querySelectorAll('form.subscribe-form, form.rr-subscribe-form, form.mt-subscribe-form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const status = statusFor(form);
      const email = form.querySelector('input[type="email"]')?.value?.trim() || '';
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
