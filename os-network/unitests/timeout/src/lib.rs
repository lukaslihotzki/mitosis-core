#![no_std]

extern crate alloc;

use krdma_test::*;
use os_network::block_on;
use os_network::future::*;
use os_network::timeout::*;

use rust_kernel_linux_util as log;
use KRdmaKit::rust_kernel_rdma_base::linux_kernel_module;

pub struct DummyFuture;

impl Future for DummyFuture {
    type Output = ();
    type Error = ();

    fn poll(&mut self) -> Poll<Self::Output, Self::Error> {
        Ok(Async::NotReady)
    }
}

#[krdma_main]
fn test_timeout() {
    let mut delay = Delay::new(500); // 500 us

    // wait for 500us
    let res = block_on(&mut delay);
    log::info!("check delay: {:?}", res);

    let dummy = DummyFuture;
    let mut timeout_dummy = Timeout::new(dummy, 400); // should timeout on 400us
    let res = block_on(&mut timeout_dummy);
    log::info!("check result: {:?}", res);
}