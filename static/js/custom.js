
  (function ($) {
  
  "use strict";

    // NAVBAR
    $('.navbar-collapse a').on('click',function(){
      $(".navbar-collapse").collapse('hide');
    });

    $(function() {
      $('.hero-slides').vegas({
          slides: [
            { src: '/static/images/slides/slide_a.jpg' },
            { src: '/static/images/slides/slide_b.jpg' },
            { src: '/static/images/slides/slide_c.jpg' },
            { src: '/static/images/slides/slide_d.jpg' },
            { src: '/static/images/slides/slide_e.jpg' },
            { src: '/static/images/slides/slide_f.jpg' },
            { src: '/static/images/slides/slide_g.jpg' },
            { src: '/static/images/slides/slide_h.jpg' }
          ],
          timer: false,
          animation: 'kenburns',
      });
    });
    
    // CUSTOM LINK
    $('.smoothscroll').click(function(){
      var el = $(this).attr('href');
      var elWrapped = $(el);
      var header_height = $('.navbar').height() + 60;
  
      scrollToDiv(elWrapped,header_height);
      return false;
  
      function scrollToDiv(element,navheight){
        var offset = element.offset();
        var offsetTop = offset.top;
        var totalScroll = offsetTop-navheight;
  
        $('body,html').animate({
        scrollTop: totalScroll
        }, 300);
      }
    });
  
  })(window.jQuery);


