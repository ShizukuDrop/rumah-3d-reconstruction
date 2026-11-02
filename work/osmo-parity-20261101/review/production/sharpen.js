// Contrast-adaptive sharpening (after AMD FidelityFX CAS) of the finished frame. The Gaussian model
// is soft; this restores edge contrast without halos: flat areas and strong edges get less, soft
// detail more. It runs after the normal render, on the display-encoded image, so splats still blend
// exactly as they were trained (rendering them into a linear target would change that).
export function createSharpener(THREE,renderer){
 const material=new THREE.ShaderMaterial({
  uniforms:{frame:{value:null},texel:{value:new THREE.Vector2()},peak:{value:0}},
  vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}',
  fragmentShader:`uniform sampler2D frame;uniform vec2 texel;uniform float peak;varying vec2 vUv;
   vec3 at(float x,float y){return texture2D(frame,vUv+vec2(x,y)*texel).rgb;}
   void main(){
    vec3 a=at(-1.,-1.),b=at(0.,-1.),c=at(1.,-1.),d=at(-1.,0.),e=at(0.,0.),f=at(1.,0.),g=at(-1.,1.),h=at(0.,1.),i=at(1.,1.);
    vec3 lo=min(min(min(d,e),min(f,b)),h),hi=max(max(max(d,e),max(f,b)),h);
    lo+=min(lo,min(min(a,c),min(g,i)));hi+=max(hi,max(max(a,c),max(g,i)));
    vec3 w=sqrt(clamp(min(lo,2.0-hi)/max(hi,1e-4),0.0,1.0))*peak;
    gl_FragColor=vec4(clamp((b*w+d*w+f*w+h*w+e)/(1.0+4.0*w),0.0,1.0),1.0);
   }`,
  depthTest:false,depthWrite:false});
 const quad=new THREE.Mesh(new THREE.PlaneGeometry(2,2),material),scene=new THREE.Scene(),camera=new THREE.Camera();
 scene.add(quad);quad.frustumCulled=false;
 let texture=null;const size=new THREE.Vector2();
 return {
  // strength 0..1 (0 leaves the frame as it is). view is the drawn area in CSS pixels, as given to
  // setViewport: letterbox bars stay untouched. Call right after rendering the frame to the canvas.
  apply(strength,view){
   renderer.getDrawingBufferSize(size);
   if(!texture||texture.image.width!==size.x||texture.image.height!==size.y){texture?.dispose();texture=new THREE.FramebufferTexture(size.x,size.y);}
   renderer.setViewport(0,0,size.x/renderer.getPixelRatio(),size.y/renderer.getPixelRatio());
   renderer.copyFramebufferToTexture(texture);
   material.uniforms.frame.value=texture;material.uniforms.texel.value.set(1/size.x,1/size.y);
   material.uniforms.peak.value=-strength/(8-3*strength);
   // Keep autoClear off, and the frame's draw-call and triangle counts, which diagnostics report.
   const autoClear=renderer.autoClear,autoReset=renderer.info.autoReset;renderer.autoClear=false;renderer.info.autoReset=false;
   renderer.setScissor(view.x,view.y,view.w,view.h);renderer.setScissorTest(true);renderer.render(scene,camera);renderer.setScissorTest(false);
   renderer.autoClear=autoClear;renderer.info.autoReset=autoReset;
  },
  dispose(){texture?.dispose();material.dispose();quad.geometry.dispose();},
 };
}
