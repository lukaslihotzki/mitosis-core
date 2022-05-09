use crate::descriptors::{Descriptor, FlatPageTable, RDMADescriptor, RegDescriptor, VMADescriptor};
use crate::kern_wrappers::mm::{PhyAddrType, VirtAddrType};
use crate::{linux_kernel_module, VmallocAllocator};
use alloc::vec::Vec;
use os_network::bytes::BytesMut;
use os_network::serialize::Serialize;

type Offset = u32;
type Value = PhyAddrType;
type PageEntry = (Offset, Value); // record the (offset, phy_addr) pair

#[derive(Clone)]
pub struct VMAPageTable {
    inner_pg_table: Vec<PageEntry, VmallocAllocator>,
}

impl Default for VMAPageTable {
    fn default() -> Self {
        Self {
            inner_pg_table: Vec::new_in(VmallocAllocator),
        }
    }
}

impl VMAPageTable {
    #[inline(always)]
    pub fn add_one(&mut self, offset: Offset, val: Value) {
        self.inner_pg_table.push((offset, val))
    }

    #[inline(always)]
    pub fn table_len(&self) -> usize {
        self.inner_pg_table.len()
    }
}

#[allow(dead_code)]
#[derive(Clone)]
pub struct FastDescriptor {
    pub regs: RegDescriptor,
    // 2-dimension matrix, each row means one page-table according to one VMA
    pub page_table: Vec<VMAPageTable, VmallocAllocator>,
    pub vma: Vec<VMADescriptor>,
    pub machine_info: RDMADescriptor,
}

impl Default for FastDescriptor {
    fn default() -> Self {
        Self {
            regs: Default::default(),
            page_table: Vec::new_in(VmallocAllocator),
            vma: Vec::new(),
            machine_info: Default::default(),
        }
    }
}

impl FastDescriptor {
    /// Transform into the flat descriptor.
    #[inline]
    pub fn to_descriptor(&self) -> Descriptor {
        let mut page_table = FlatPageTable::new();

        for (vma_idx, vma_pg_table) in self.page_table.iter().enumerate() {
            let start = self.vma[vma_idx].get_start();
            for (offset, phy_addr) in &vma_pg_table.inner_pg_table {
                page_table.add_one((*offset as VirtAddrType + start) as _, *phy_addr as _);
            }
        }

        Descriptor {
            regs: self.regs.clone(),
            page_table,
            vma: self.vma.clone(),
            machine_info: self.machine_info.clone(),
        }
    }
}

impl FastDescriptor {
    #[inline]
    fn vma_pg_table_serialization_buf_len(&self) -> usize {
        let mut result = core::mem::size_of::<usize>();
        // note that each vma offset-page-table may have different entry length !
        for vma_pg_table in &self.page_table {
            result += vma_pg_table.serialization_buf_len();
        }
        result
    }
}

impl os_network::serialize::Serialize for VMAPageTable {
    /// Serialization format:
    /// ```
    /// | inner_pg_table length in bytes <-8 bytes-> | inner_pg_table entries|
    /// ```
    fn serialize(&self, bytes: &mut BytesMut) -> bool {
        if bytes.len() < self.serialization_buf_len() {
            crate::log::error!(
                "failed to serialize: buffer space not enough. Need {}, actual {}",
                self.serialization_buf_len(),
                bytes.len()
            );
            return false;
        }
        let mut cur = unsafe { bytes.truncate_header(0).unwrap() };
        let sz = unsafe {
            cur.memcpy_serialize_at(0, &self.inner_pg_table.len())
                .unwrap()
        };
        cur = unsafe { cur.truncate_header(sz).unwrap() };
        if core::mem::size_of::<Offset>() < core::mem::size_of::<VirtAddrType>()
            && self.table_len() % 2 == 1
        {
            let pad: u32 = 0;
            let sz = unsafe { cur.memcpy_serialize_at(0, &pad).unwrap() };
            cur = unsafe { cur.truncate_header(sz).unwrap() };
        }

        for (offset, _) in self.inner_pg_table.iter() {
            let sz0 = unsafe { cur.memcpy_serialize_at(0, offset).unwrap() };
            cur = unsafe { cur.truncate_header(sz0).unwrap() };
        }

        for (_, paddr) in self.inner_pg_table.iter() {
            let sz1 = unsafe { cur.memcpy_serialize_at(0, paddr).unwrap() };
            cur = unsafe { cur.truncate_header(sz1).unwrap() };
        }
        true
    }

    fn deserialize(bytes: &BytesMut) -> core::option::Option<Self> {
        let mut res: Vec<PageEntry, VmallocAllocator> = Vec::new_in(VmallocAllocator);
        let mut count: usize = 0;
        let mut cur = unsafe { bytes.truncate_header(0).unwrap() };

        let off = unsafe { cur.memcpy_deserialize(&mut count)? };

        cur = unsafe { cur.truncate_header(off)? };

        if core::mem::size_of::<Offset>() < core::mem::size_of::<VirtAddrType>() && count % 2 == 1 {
            let mut pad: u32 = 0;
            let off = unsafe { cur.memcpy_deserialize(&mut pad)? };
            cur = unsafe { cur.truncate_header(off)? };
        }

        for _ in 0..count {
            let mut virt: Offset = 0;
            let sz0 = unsafe { cur.memcpy_deserialize_at(0, &mut virt)? };
            res.push((virt, 0));
            cur = unsafe { cur.truncate_header(sz0)? };
        }

        for i in 0..count {
            let mut phy: Value = 0;
            let sz1 = unsafe { cur.memcpy_deserialize_at(0, &mut phy)? };
            res[i].1 = phy;
            cur = unsafe { cur.truncate_header(sz1)? };
        }

        Some(VMAPageTable {
            inner_pg_table: res,
        })
    }

    fn serialization_buf_len(&self) -> usize {
        let mut base = core::mem::size_of::<usize>()
            + self.inner_pg_table.len()
                * (core::mem::size_of::<Offset>() + core::mem::size_of::<Value>());
        if core::mem::size_of::<Offset>() < core::mem::size_of::<VirtAddrType>()
            && self.table_len() % 2 == 1
        {
            base += core::mem::size_of::<u32>();
        }
        base
    }
}

impl os_network::serialize::Serialize for FastDescriptor {
    /// Serialization format:
    /// ```
    /// | RegDescriptor <-sizeof(RegDescriptor)->
    /// | VMA page table length in bytes <-8 bytes-> | VMAPageMap
    /// | VMA descriptor length in bytes <-8 bytes-> | VMA descriptor
    /// | RDMADescriptor |
    /// ```
    fn serialize(&self, bytes: &mut BytesMut) -> bool {
        if bytes.len() < self.serialization_buf_len() {
            crate::log::error!(
                "failed to serialize: buffer space not enough. Need {}, actual {}",
                self.serialization_buf_len(),
                bytes.len()
            );
            return false;
        }

        // 1. Reg
        let mut cur = unsafe { bytes.truncate_header(0).unwrap() };
        self.regs.serialize(&mut cur);
        let mut cur = unsafe {
            // update cursor
            cur.truncate_header(self.regs.serialization_buf_len())
                .unwrap()
        };

        // 2. page table (size)
        let sz = unsafe { cur.memcpy_serialize_at(0, &self.page_table.len()).unwrap() };
        let mut cur = unsafe { cur.truncate_header(sz).unwrap() };
        //   page table (vec)
        for vma_pg_table in &self.page_table {
            // size of each VMA page table.
            // let sz = unsafe { cur.memcpy_serialize_at(0, &vma_pg_table.inner_pg_table.len()).unwrap() };
            // cur = unsafe { cur.truncate_header(sz).unwrap() };

            vma_pg_table.serialize(&mut cur);
            cur = unsafe {
                cur.truncate_header(vma_pg_table.serialization_buf_len())
                    .unwrap()
            };
        }

        // 3. vmas
        let sz = unsafe { cur.memcpy_serialize_at(0, &self.vma.len()).unwrap() };
        let mut cur = unsafe { cur.truncate_header(sz).unwrap() };

        for vma in &self.vma {
            vma.serialize(&mut cur);
            cur = unsafe { cur.truncate_header(vma.serialization_buf_len()).unwrap() };
        }
        // 4. finally, machine info
        self.machine_info.serialize(&mut cur);

        true
    }

    fn deserialize(bytes: &BytesMut) -> core::option::Option<Self> {
        let mut cur = unsafe { bytes.truncate_header(0).unwrap() };
        // regs
        let regs = RegDescriptor::deserialize(&cur)?;
        cur = unsafe { cur.truncate_header(regs.serialization_buf_len())? };

        // vma pt
        let mut pt = Vec::new_in(VmallocAllocator);
        // VMA page table count
        let mut count: usize = 0;
        let off = unsafe { cur.memcpy_deserialize(&mut count)? };
        cur = unsafe { cur.truncate_header(off)? };

        for _ in 0..count {
            let vma_pg_table = VMAPageTable::deserialize(&cur)?;
            cur = unsafe { cur.truncate_header(vma_pg_table.serialization_buf_len())? };
            pt.push(vma_pg_table);
        }
        // vmas
        let mut vmas = Vec::new();
        let mut count: usize = 0;
        let off = unsafe { cur.memcpy_deserialize(&mut count)? };
        cur = unsafe { cur.truncate_header(off)? };

        for _ in 0..count {
            let vma = VMADescriptor::deserialize(&cur)?;
            cur = unsafe { cur.truncate_header(vma.serialization_buf_len())? };
            vmas.push(vma);
        }
        let machine_info = RDMADescriptor::deserialize(&cur)?;

        Some(Self {
            regs,
            page_table: pt,
            vma: vmas,
            machine_info,
        })
    }

    fn serialization_buf_len(&self) -> usize {
        self.regs.serialization_buf_len()
            + self.vma_pg_table_serialization_buf_len()
            + core::mem::size_of::<usize>() // the number of VMA descriptors
            + self.vma.len() * core::mem::size_of::<VMADescriptor>()
            + self.machine_info.serialization_buf_len()
    }
}