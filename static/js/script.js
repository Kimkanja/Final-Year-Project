const sign_in_btn = document.querySelector("#sign-in-btn");
const sign_up_btn = document.querySelector("#sign-up-btn");
const container = document.querySelector(".container");

sign_up_btn.addEventListener('click', () =>{
    container.classList.add("sign-up-mode");
});

sign_in_btn.addEventListener('click', () =>{
    container.classList.remove("sign-up-mode");
});

/* Home JS */
const feed = document.getElementById("feed");
let page = 1;
let loading = false;

async function loadPosts() {
  if (loading) return;
  loading = true;

  const response = await fetch(`/api/posts?page=${page}`);
  const data = await response.json();

  data.posts.forEach(post => {
    const postElement = document.createElement("div");
    postElement.classList.add("post");

    postElement.innerHTML = `
      <div class="post-header">${post.username}</div>
      <img src="${post.image_url}" class="post-image">
      <div class="post-caption">${post.caption}</div>
    `;

    feed.appendChild(postElement);
  });

  page++;
  loading = false;
}

window.addEventListener("scroll", () => {
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 200) {
    loadPosts();
  }
});

loadPosts();

const hamburger = document.getElementById('hamburger');
let menuOpen = false;

hamburger.addEventListener('click', () => {
  let mobileMenu = document.querySelector('.mobile-menu');
  
  // create menu if it doesn't exist
  if (!mobileMenu) {
    mobileMenu = document.createElement('div');
    mobileMenu.classList.add('mobile-menu');
    mobileMenu.innerHTML = document.querySelector('.sidebar .menu').outerHTML;
    document.body.appendChild(mobileMenu);
  }

  // toggle menu
  if (menuOpen) {
    mobileMenu.style.display = 'none';
  } else {
    mobileMenu.style.display = 'block';
  }

  menuOpen = !menuOpen;
});
